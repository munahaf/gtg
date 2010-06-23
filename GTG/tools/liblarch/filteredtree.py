# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Gettings Things Gnome! - a personal organizer for the GNOME desktop
# Copyright (c) 2008-2009 - Lionel Dricot & Bertrand Rousseau
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.
# -----------------------------------------------------------------------------
#
"""
FilteredTree provides a filtered view (subset) of tasks

FilteredTree
============
The problem we have is that, sometimes, we don't want to display all tasks.
We want tasks to be filtered (workview, tags, …)

The expected approach would be to put a gtk.TreeModelFilter above our
TaskTree. Unfortunately, this doesn't work because TreeModelFilter hides
all children of hidden nodes (not what we want!)

The solution we have found is to insert a fake tree between Tree and
TaskTree.  This fake tree is called FilteredTree and maps path and node
methods to a result corresponding to the filtered tree.

Note that the nodes are not aware that they are in a filtered tree.
Use the FilteredTree methods, not the node methods directly.
If you believe a function would be useful in a filtered tree, don't 
hesitate to make a proposal.

To be more efficient, a quick way to optimize the FilteredTree is to cache
all answers in a dictionary so we don't have to compute the answer 
all the time. This is not done yet.

B{Warning}: this is very fragile. Calls to any GTK registered view should be
perfecly in sync with changes in the underlying model.
We definitely should develop some unit tests for this class.

Structure of the source:

 1. Standard tree functions mapping (get_node, get_all_nodes, get_all_keys)
 2. Receiving signal functions ( task-added,task-modified,task-deleted)
 3. Treemodel helper functions. To make it easy to build a treemodel on top.
 4. Filtering : is_displayed() and refilter()
 5. Changing the filters (not for the main FilteredTree)
 6. Private helpers.

There's one main FilteredTree that you can get through the requester. This
main FilteredTree uses the filters applied throughout the requester. This
allows plugin writers to easily get the current displayed tree (main view).

You can create your own filters on top of this main FilteredTree, or you
can create your own personal FilteredTree custom view and apply your own
filters on top of it without interfering with the main view.  (This is
how the closed tasks pane is currently built.)

For custom views, the plugin writers are able to get their own
FilteredTree and apply on it the filters they want. (this is not finished
yet but in good shape).

An important point to stress is that information needs to be passed from
bottom to top, with no horizontal communication at all between views.

"""

import gobject

from GTG.tools.logger import Log

COUNT_CACHING_ENABLED = True

class FilteredTree(gobject.GObject):

    #Those are the three signals you want to catch if displaying
    #a filteredtree. The argument of all signals is the tid of the task
    __gsignals__ = {'task-added-inview': (gobject.SIGNAL_RUN_FIRST, \
                                          gobject.TYPE_NONE, (str, )),
                    'task-deleted-inview': (gobject.SIGNAL_RUN_FIRST, \
                                            gobject.TYPE_NONE, (str, )),
                    'task-modified-inview': (gobject.SIGNAL_RUN_FIRST, \
                                            gobject.TYPE_NONE, (str, )),}

    def __init__(self,tree,filtersbank,refresh=True):
        """
        Construct a FilteredTree object on top of an existing task tree.
        @param req: The requestor object
        @param tree: The tree to filter from
        @param maintree: Whether this tree is the main tree.  The requester
        must be used to change filters against the main tree.
        """
        gobject.GObject.__init__(self)
        self.applied_filters = []
        self.tree = tree
        self.fbank = filtersbank
        self.update_count = 0
        self.add_count = 0
        self.remove_count = 0
        self.__nodes_count = 0
        self.flat = False
        #virtual root is the list of root nodes
        #initially, they are the root nodes of the original tree
        self.virtual_root = []
        self.displayed_nodes = []
        #This is for profiling
#        self.using_cache = 0
        #useful for temp storage :
        self.node_to_add = []
        self.__adding_queue = []
        self.__adding_lock = False
        self.tasks_to_modify = []
        self.node_to_remove = []
        self.__clean_list = []
        #an initial refilter is always needed if we don't apply a filter
        #for performance reason, we do it only if refresh = True
        self.__reset_cache()
        if refresh:
            self.refilter()
        #connecting
        self.tree.connect("node-added", self.__task_added)
        self.tree.connect("node-modified", self.__task_modified)
        self.tree.connect("node-deleted", self.__task_deleted)

    def __reset_cache(self):
        self.path_for_node_cache = {}
        self.counted_nodes = []
        self.count_cache = {}

    #### Standard tree functions
    def get_node(self,id):
        """
        Retrieves the given node
        @param id: The tid of the task node
        @return: Node from the underlying tree
        """
        return self.tree.get_node(id)
    
    def get_root(self):
        """
        returns the root node
        """
        return self.tree.get_root()
        
    def get_all_nodes(self):
        """
        returns list of all displayed node keys
        """
        return list(self.displayed_nodes)

        
    def get_n_nodes(self,withfilters=[],transparent_filters=True):
        """
        returns quantity of displayed nodes in this tree
        if the withfilters is set, returns the quantity of nodes
        that will be displayed if we apply those filters to the current
        tree. It means that the currently applied filters are also taken into
        account.
        If transparent_filters=False, we only take into account the applied filters
        that doesn't have the transparent parameters.
        """
        toreturn = 0
        usecache = False
        if transparent_filters:
            #Currently, the cache only work for one filter
            if len(withfilters) == 1:
                usecache = True
            zelist = self.counted_nodes
        else:
            zelist = self.displayed_nodes
        if len(withfilters) > 0:
            key = "".join(withfilters)
            if usecache and self.count_cache.has_key(key):
                toreturn = self.count_cache[key]
#                self.using_cache += 1
#                print "we used cache %s" %(self.using_cache)
            else:
                for tid in zelist:
                    result = True
                    for f in withfilters:
                        filt = self.fbank.get_filter(f)
                        if filt:
                            result = result and filt.is_displayed(tid)
                    if result:
                        toreturn += 1
                if COUNT_CACHING_ENABLED and usecache:
                    self.count_cache[key] = toreturn
        else:
            toreturn = len(zelist)
        return toreturn
        
    ### signals functions
    def __task_added(self,sender,tid):
        todis = self.__is_displayed(tid)
        curdis = self.is_displayed(tid)
        if todis and not curdis:
            self.__add_node(tid)
        
    def __task_modified(self,sender,tid):
        if tid not in self.tasks_to_modify:
            self.tasks_to_modify.append(tid)
            inroot = self.__is_root(tid)
            self.__update_node(tid,inroot)
            self.tasks_to_modify.remove(tid)

    def __task_deleted(self,sender,tid):
        self.__remove_node(tid)
        
    ####TreeModel functions ##############################

    def print_tree(self):
        print "displayed : %s" %self.displayed_nodes
        for rid in self.virtual_root:
            r = self.tree.get_node(rid)
            self.__print_from_node(r)

    #The path received is only for tasks that are displayed
    #We have to find the good node.
    def get_node_for_path(self, path):
        """
        Returns node for the given path.
        """
        #We should convert the path to the base.path
        if not path or str(path) == '()':
            return self.tree.get_root()
        p0 = path[0]
        if len(self.virtual_root) > p0:
            n1id = self.virtual_root[p0]
            n1 = self.get_node(n1id)
            pa = path[1:]
            toreturn = self.__node_for_path(n1,pa)
        else:
            toreturn = None
        return toreturn

    def __node_for_path(self,basenode,path):
        if len(path) == 0 or self.flat:
            return basenode
        elif path[0] < self.node_n_children(basenode):
            if len(path) == 1:
                return self.node_nth_child(basenode,path[0])
            else:
                node = self.node_nth_child(basenode,path[0])
                path = path[1:]
                return self.__node_for_path(node, path)
        else:
            return None

    def get_paths_for_node(self, node):
        """
        Return a list of paths for a given node
        Return an empty list if no path for that Node.
        """
        toreturn = []
        if node:
            tid = node.get_id()
            pars = self.node_parents(node)
        #For that node, we should convert the base_path to path
        if not node or not self.is_displayed(node.get_id()):
            return toreturn
        #This is the cache so we don't compute it all the time
        #TODO: this is commented out as it still doesn't work with filter
#        elif self.path_for_node_cache.has_key(tid):
#            return self.path_for_node_cache[tid]
        elif node == self.get_root():
            path = ()
            toreturn.append(path)
#        elif tid in self.virtual_root:
        elif len(pars) <= 0:
            if tid in self.virtual_root:
                ind = self.virtual_root.index(tid)
                path = (ind,)
                toreturn.append(path)
            else:
                print "*** *** %s has parents but is not in VR" %tid
                print "*** is in nodes to add %s ? " %(tid in self.node_to_add)
                
#            parents = self.node_parents(node)
#            if len(parents) > 0:
#                print "WARNING :  %s was in VR with %s parents" %(tid,len(parents))
        #The node is not a virtual root
        else:
#            if len(pars) <= 0:
#                #if we don't have parent, we add the task
#                #to the virtual root.
#                if tid in DEBUG_TID:
#                    print "we should not update %s from the get_path method" %tid
#                self.__root_update(tid,True)
#                ind = self.virtual_root.index(tid)
#                path = (ind,)
#                toreturn.append(path)
#            else:
            for par in pars:
                pos = 0
                max = self.node_n_children(par)
                child = self.node_children(par)
                while pos < max and node != child:
                    pos += 1
                    child = self.node_nth_child(par,pos)
                par_paths = self.get_paths_for_node(par)
                for par_path in par_paths:
                    path = par_path + (pos,)
                    toreturn.append(path)
            if len(toreturn) == 0:
                #if we are here, it means that we have a ghost task that 
                #is not really displayed but still here, in the tree
                #it happens sometimes when we remove a parent with children
                #if we still have a recorded path for the ghost task,
                #we return it. This provides ghost task from staying displayed
                if self.path_for_node_cache.has_key(tid):
                    toreturn = self.path_for_node_cache[tid]
                else:
                    print "ghost position for %s" %tid
                    print "VR : %s " %self.virtual_root
                    print self.path_for_node_cache
                    
        self.path_for_node_cache[tid] = toreturn
        return toreturn

    #Done
    def next_node(self, node,parent):
        """
        Returns the next sibling node, or None if there are no other siblings
        """
        #We should take the next good node, not the next base node
        nextnode = None
        if node:
            tid = node.get_id()
            if tid in self.virtual_root:
                i = self.virtual_root.index(tid) + 1
                if len(self.virtual_root) > i:
                    nextnode_id = self.virtual_root[i]
                    if self.is_displayed(nextnode_id):
                        nextnode = self.get_node(nextnode_id)
            else:
                parents_nodes = self.node_parents(node)
                if len(parents_nodes) >= 1:
                    if parent in parents_nodes:
                        parent_node = parent
                    else:
                        parent_node = parents_nodes[0]
                    total = self.node_n_children(parent)
                    c = 0
                    next_id = None
                    while c < total and not next_id:
                        child = self.node_nth_child(parent,c)
                        c += 1
                        if child == node:
                            next_id = c
                    if next_id < total:
                        nextnode = self.node_nth_child(parent,next_id)
        #check to see if our result is correct
        if nextnode and not self.is_displayed(nextnode.get_id()):
            nextnode = None
        return nextnode

    #Done
    def node_children(self, parent):
        """
        Returns the first child node of the given parent, or None
        if the parent has no children.
        @param parent: The parent node or None to retrieve the children
        of the virtual root.
        """
        #print "on_iter_children for parent %s" %parent.get_id()
        #here, we should return only good childrens
        child = self.node_nth_child(parent,0)
        return child

    #Done
    def node_has_child(self, node):
        """
        Returns true if the given node has any children
        """
        #print "on_iter_has_child for node %s" %node
        #we should say "has_good_child"
#        print "node has %s children" %self.node_n_children(node)
        if not self.flat and node and self.node_n_children(node)>0:
            return True
        else:
            if not node:
                print "NODE IS NULL, we should maybe return True"
            return False

    #Done
    def node_n_children(self, node):
        """
        Returns number of children for the given node
        """
        #we should return the number of "good" children
        if not node:
            toreturn = len(self.virtual_root)
            id = 'root'
        elif self.flat:
            toreturn = 0
        else:
            n = 0
            for cid in node.get_children():
                if self.is_displayed(cid):
                    n+= 1
            toreturn = n
        return toreturn

    #Done
    def node_nth_child(self, node, n):
        """
        Retrieves the nth child of the node.
        @param node: The parent node, or None to look at children of the
        virtual_root.
        """
        #we return the nth good children !
        if not node:
            if len(self.virtual_root) > n:
                to_id = self.virtual_root[n]
                toreturn = self.get_node(to_id)
#                print "## node_nth_child : %s" %to_id
            else:
                toreturn = None
        elif self.flat:
            #If we are flat, nobody has children
            toreturn = None
        else:
            total = node.get_n_children()
            cur = 0
            good = 0
            toreturn = None
            while good <= n and cur < total:
                curn = node.get_nth_child(cur)
                if curn and self.is_displayed(curn.get_id()):
                    cid = curn.get_id()
                    if good == n:
                        toreturn = curn
                        #if we have a child, it cannot be in the root
#                        if cid in self.virtual_root:
##                            isroot = self.__is_root(curn)
#                            print "*** children %s of task %s is also in VR" \
#                                                    %(cid,node.get_id())
#                            print "   we will correct that error now"
#                            self.__root_update(cid,False)
                    good += 1
                cur += 1
        return toreturn

    #Done
    def node_parents(self, node):
        """
        Returns parent of the given node, or None if there is no 
        parent (such as if the node is a child of the virtual root),
        or if the parent is not displayable.
        """
        #return None if we are at a Virtual root
        parents_nodes = []
        if node == None:
            Log.debug("requested a parent of a non-existing node")
            return parents_nodes
        tid = node.get_id()
#        if node and tid in self.virtual_root:
#            return parents_nodes
        #we return only parents that are not root and displayed
        if node and node.has_parent():
            for pid in node.get_parents():
                parent = self.tree.get_node(pid)
#                if pid in DEBUG_TID:
#                    print "%%%%parent %s is displayed : %s" %(pid,self.is_displayed(pid))
                if self.is_displayed(pid) and parent != self.tree.get_root():
                    parents_nodes.append(parent)
#            if len(parents_nodes) == 0:
#                print "ERROR : %s has no parent and is not in VR" %tid
#        if not self.flat and tid in self.virtual_root and len(parents_nodes) > 0:
#            self.__root_update(tid,False)
#        if tid in DEBUG_TID:
#            print "%s has parents %s but return %s" %(tid,node.get_parents(),parents_nodes)
        return parents_nodes


    #### Filtering methods #########
    
    def is_displayed(self,tid):
        """
        This is a public method that return True if the task is
        currently displayed in the tree
        """
        if tid:
            toreturn = tid in self.displayed_nodes
        else:
            toreturn = False
        return toreturn
    
    def __is_displayed(self, tid):
        """
        This is a private method that return True if the task *should*
        be displayed in the tree, regardless of its current status
        """
        if tid:
            result = True
            counting_result = True
            cache_key = ""
            for f in self.applied_filters:
                filt = self.fbank.get_filter(f)
                cache_key += f
                if filt:
                    temp = filt.is_displayed(tid)
                    result = result and temp
                    if not filt.get_parameters('ignore_when_counting'):
                        counting_result = counting_result and temp
            if counting_result and tid not in self.counted_nodes:
                #This is an hard custom optimisation for task counting
                #Normally, we would here reset the cache of counted tasks
                #But this slow down a lot the startup.
                #So, we update manually the cache.
                for k in self.count_cache.keys():
                    f = self.fbank.get_filter(k)
                    if f.is_displayed(tid):
                        self.count_cache[k] += 1
                self.counted_nodes.append(tid)
            elif not counting_result and tid in self.counted_nodes:
                #Removing node is less critical so we just reset the cache.
                self.count_cache = {}
                self.counted_nodes.remove(tid)
        else:
            result = False
        return result
        
    def refilter(self):
        """
        rebuilds the tree from scratch. It should be called only when 
        the filter is changed (i.e. only filters_bank should call it).
        """
        self.update_count = 0
        self.add_count = 0
        self.remove_count = 0
        virtual_root2 = []
        to_add = []
#        self.counted_nodes = []
#        self.count_cache = {}
        self.__reset_cache()
        #If we have only one flat filter, the result is flat
        self.flat = False
        for f in self.applied_filters:
            filt = self.fbank.get_filter(f)
            if filt and not self.flat:
                self.flat = filt.is_flat()
        #First things, we list the nodes that will be
        #ultimately displayed
        for nid in self.tree.get_all_nodes():
            if self.__is_displayed(nid):
                to_add.append(nid)
        #Second step, we empty the current tree as we will rebuild it
        #from scratch
        for rid in list(self.virtual_root):
            n = self.get_node(rid)
            self.__clean_from_node(n)
        #We reinitialize the tree before adding nodes that should be added
        self.displayed_nodes = []
        for nid in list(to_add):
            self.__add_node(nid)
        #end of refiltering
#        print "*** end of refiltering ****"
#        self.print_tree()

    ####### Change filters #################
    def apply_filter(self,filter_name,parameters=None,\
                     reset=False,imtherequester=False,refresh=True):
        """
        Applies a new filter to the tree.  Can't be called on the main tree.
        @param filter_name: The name of an already registered filter to apply
        @param parameters: Optional parameters to pass to the filter
        @param reset : optional boolean. Should we remove other filters?
        @param imtherequester: If true enables adding filters to the main tree
        """
        if reset:
            self.applied_filters = []
        if parameters:
            filt = self.fbank.get_filter(filter_name)
            if filt:
                filt.set_parameters(parameters)
        if filter_name not in self.applied_filters:
            self.applied_filters.append(filter_name)
            if refresh:
                self.refilter()
            return True
        else:
            return False
    
    def unapply_filter(self,filter_name,imtherequester=False,refresh=True):
        """
        Removes a filter from the tree.  Can't be called on the main tree.
        @param filter_name: The name of an already added filter to remove
        @param imtherequester: If true enables removing filters from the main tree
        """
        if filter_name in self.applied_filters:
            self.applied_filters.remove(filter_name)
            if refresh:
                self.refilter()
            return True
        else:
            return False

    def reset_filters(self,imtherequester=False,refresh=True):
        """
        Clears all filters currently set on the tree.  Can't be called on 
        the main tree.
        @param imtherequester: If true enables clearing filters from the main tree
        """
        self.applied_filters = []
        if refresh:
            self.refilter()

    def reset_tag_filters(self,refilter=True,imtherequester=False):
        """
        Clears all filters currently set on the tree.  Can't be called on 
        the main tree.
        @param imtherequester: If true enables clearing filters from the main tree
        """
        if "notag" in self.applied_filters:
            self.applied_filters.remove('notag')
        if "no_disabled_tag" in self.applied_filters:
            self.applied_filters.remove('no_disabled_tag')
        for f in self.applied_filters:
            if f.startswith('@'):
                self.applied_filters.remove(f)
        if refilter:
            self.refilter()

    ####### Private methods #################

    # Return True if the node should be a virtual root node
    # regardless of the current state
    def __is_root(self,nid):
        is_root = True
        n = self.tree.get_node(nid)
        if n and not self.flat and n.has_parent():
            for par in n.get_parents():
                if self.__is_displayed(par):
                    is_root = False
        return is_root
    
    # Put or remove a node from the virtual root
    def __root_update(self,tid,inroot):
#        if tid in DEBUG_TID:
#            print "calling root update %s for %s" %(inroot,tid)
        children_update = False
        if inroot:
            if tid not in self.virtual_root:
#                if tid in DEBUG_TID:
#                    print "appending %s to VR" %tid
                self.virtual_root.append(tid)
                #We will also update the children of that node
                children_update = True
        else:
            if tid in self.virtual_root:
#                if tid in DEBUG_TID:
#                    print "removin %s from VR" %tid
                self.virtual_root.remove(tid)
            #even if you are not a root, 
            #your children should not be in VR either
            else:
                children_update = True
        #now we handle childrens
        if not self.flat and children_update:
            node = self.get_node(tid)
            nc = self.node_n_children(node)
#            if tid in DEBUG_TID:
#                print "updating %s childrens of node %s" %(nc,tid)
            i = 0
            while i < nc:
                ch = self.node_nth_child(node,i)
                if ch:
                    chid = ch.get_id()
                    if chid in self.virtual_root:
                        #the child was in the VR. It should not be
                        #because its parent is in now
                        self.__update_node(chid,False)
                i += 1
    
    def __update_node(self,tid,inroot):
        if tid not in self.node_to_remove:
#            if tid in DEBUG_TID:
#                print "updating inroot %s the node %s" %(inroot,tid)
            todis = self.__is_displayed(tid) 
            curdis = self.is_displayed(tid)
            if todis:
                #if the task was not displayed previously but now should
                #we add it.
                if not curdis:
#                    if tid in DEBUG_TID:
#                        print "*update_node : adding node %s" %tid
                    self.__add_node(tid)
                else:
                    self.__root_update(tid,inroot)
                    self.update_count += 1
                    self.emit("task-modified-inview", tid)
                    #I don't remember why we have to update the children.
                    if not self.flat:
                        node = self.get_node(tid)
                        if node:
                            child_list = node.get_children()
                            for c in child_list:
                                self.__update_node(c,False)
            else:
                #if the task was displayed previously but shouldn't be anymore
                #we remove it
                if curdis:
                    self.__remove_node(tid)
                else:
                    self.emit("task-deleted-inview", tid)


    
    
    def __add_node(self,tid,inroot=None):
        self.__adding_queue.append([tid,inroot])
        if tid and not self.__adding_lock and len(self.__adding_queue) > 0:
            self.__adding_lock = True
            self.__adding_loop()

    def __adding_loop(self):
        while len(self.__adding_queue) > 0:
            tid,inroot = self.__adding_queue.pop(0)
            if not self.is_displayed(tid):
    #            if tid in DEBUG_TID:
    #                print "adding inroot %s the node %s" %(inroot,tid)
                node = self.tree.get_node(tid)
                if inroot == None:
                    inroot = self.__is_root(tid)
                #If the parent's node is not already displayed, we wait
                #(the len of parents is 0 means no parent dislayed)
                parents = self.node_parents(node)
                if not inroot and len(parents) <= 0:
                    if tid not in self.node_to_add:
                        self.node_to_add.append(tid)
                elif inroot and len(parents) > 0:
                    #"we add to the root a task with parents !!!!!"
                    if tid not in self.node_to_add:
                        self.node_to_add.append(tid)
                else:
                    self.add_count += 1
                    self.__nodes_count += 1
                    self.displayed_nodes.append(tid)
                    if tid in self.node_to_add:
                        self.node_to_add.remove(tid)
                    #Should be in displayed_nodes before updating the root
                    self.__root_update(tid,inroot)
                    self.emit("task-added-inview", tid)
                    #We added a new node so we can check with those waiting
                    lost_nodes = []
                    while len(self.node_to_add) > 0:
                        nid = self.node_to_add.pop(0)
                        toad = self.get_node(nid)
                        if len(self.node_parents(toad)) > 0:
                            self.__add_node(nid,False)
                        else:
                            lost_nodes.append(nid)
                    self.node_to_add += lost_nodes
        self.__adding_lock = False
    
    def __remove_node(self,tid):
        if tid not in self.node_to_remove:
            self.node_to_remove.append(tid)
            isroot = False
            if tid in self.displayed_nodes:
                isroot = self.__is_root(tid)
                self.remove_count += 1
                self.__nodes_count -= 1
                self.emit('task-deleted-inview',tid)
                self.__root_update(tid,False)
                self.displayed_nodes.remove(tid)
            if tid in self.counted_nodes:
                self.counted_nodes.remove(tid)
                self.count_cache = {}
            #Test if this is necessary
            parent = self.node_parents(self.get_node(tid))
            #we don't need to update parents if the node is root
            #this might happen with flat filter
            if not isroot:
                for p in parent:
                    pid = p.get_id()
                    if pid not in self.__clean_list:
                        inroot = self.__is_root(pid)
                        self.__update_node(pid,inroot)
            self.node_to_remove.remove(tid)
        
    #This function print the actual tree. Useful for debugging
    def __print_from_node(self, node, prefix=""):
        print "%s%s    (%s) " %(prefix,node.get_id(),\
                    str(self.get_paths_for_node(node)))
        prefix = prefix + "->"
        if self.node_has_child(node):
            child = self.node_children(node)
            nn = self.node_n_children
            n = 0
            while child and n < nn:
                n += 1
                self.__print_from_node(child,prefix)
                child = self.node_nth_child(node,n)
    
    #This function removes all the nodes, leaves first.
    def __clean_from_node(self, node):
        nid = node.get_id()
        if nid not in self.__clean_list:
            self.__clean_list.append(nid)
            if self.node_has_child(node):
                n = self.node_n_children(node)
                child = self.node_nth_child(node,n-1)
                while child and n > 0:
                    self.__clean_from_node(child)
                    n = n-1
                    child = self.node_nth_child(node,n-1)
            self.__remove_node(nid)
            self.__clean_list.remove(nid)