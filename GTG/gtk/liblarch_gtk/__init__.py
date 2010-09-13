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

#useful for debugging purpose.
#Disabling that will disable the TreeModelSort on top of our TreeModel
ENABLE_SORTING = True

import gtk
import gobject

from GTG.gtk.liblarch_gtk.treemodel import TreeModel

DND_TARGETS = [
        ('gtg/task-iter-str', gtk.TARGET_SAME_WIDGET, 0)
    ]

class TreeView(gtk.TreeView):

    __string_signal__ = (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (str, ))
    __gsignals__ = {'node-expanded' : __string_signal__, \
                    'node-collapsed': __string_signal__, \
                    }


    def __emit(self,sender,iter,path,data=None):
        #don't ask me why but it seems that iter is not valid.
        #we will then retrieve another iter using the path
        itera = self.treemodel.get_iter(path)
        if self.treemodel.iter_is_valid(itera):
            nid = self.treemodel.get_value(itera,0)
            if data == 'expanded':
                self.emit('node-expanded',nid)
            elif data == 'collapsed':
                self.emit('node-collapsed',nid)
        else:
            print "sending %s for invalid iter %s" %(data,path)

    def show(self):
        gtk.TreeView.show(self)
        self.basetreemodel.connect_model()

    def __init__(self, tree, description):
        gtk.TreeView.__init__(self)
        self.columns = {}
        self.bg_color_func = None
        self.bg_color_column = None
        self.separator_func = None

        self.basetree = tree
        #We build the model
        self.basetreemodel = TreeModel(tree)
        #We apply a treemodelsort on top of it
        if ENABLE_SORTING:
            self.treemodel = gtk.TreeModelSort(self.basetreemodel)
        else:
            self.treemodel = self.basetreemodel
        self.order_of_col = {}
        self.connect('row-expanded',self.__emit,'expanded')
        self.connect('row-collapsed',self.__emit,'collapsed')

        #Building a list of ordered columns
        for col_name in description:
            last = 9999
            desc = description[col_name]
            if desc.has_key('order'):
                order = desc['order']
            else:
                order = last
                last += 1
            self.order_of_col[order] = col_name

        for col_nbr in sorted(self.order_of_col.keys()):
            col_name = self.order_of_col[col_nbr]
            desc = description[col_name]
            col_nbr = self.basetreemodel.add_col(desc['value'])
            if desc.get('new_column',True):
                col = gtk.TreeViewColumn()
                newcol = True
            else:
                newcol = False
            self.columns[col_name] = [col_nbr,col]
            if desc.has_key('renderer'):
                renderer = desc["renderer"][1]
                rend_attribute = desc["renderer"][0]
            else:
                raise ValueError("The treeview description should have a renderer")
            #Those are default value that can be changed later
            if desc.has_key('expandable'):
                expand = desc['expandable']
            else:
                expand = False
            if desc.has_key('resizable'):
                resizable = desc['resizable']
            else:
                resizable = True
            if desc.has_key('visible'):
                visible = desc['visible']
            else:
                visible = True
            col.set_visible(visible)
            #title is not mandatory
            if desc.has_key('title'):
                col.set_title(desc['title'])
            col.pack_start(renderer, expand=expand)
            col.add_attribute(renderer, rend_attribute, col_nbr)
            #By default, resizable
            col.set_resizable(resizable)
            col.set_expand(expand)
            col.set_cell_data_func(renderer, self._celldatafunction)
            if ENABLE_SORTING:
                if desc.has_key('sorting'):
                    sort_nbr = self.columns[desc['sorting']][0]
                    col.set_sort_column_id(sort_nbr)
                if desc.has_key('sorting_func'):
                    self.treemodel.set_sort_func(col_nbr,self._sort_func,\
                                                        desc['sorting_func'])
                    col.set_sort_column_id(col_nbr)
            if newcol:
                self.append_column(col)

        self.set_model(self.treemodel)
        
        # Drag and drop initialization
        self.enable_model_drag_source(\
            gtk.gdk.BUTTON1_MASK,
            DND_TARGETS,
            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_MOVE)
        self.enable_model_drag_dest(\
            DND_TARGETS,
            gtk.gdk.ACTION_DEFAULT)
        self.drag_source_set(\
            gtk.gdk.BUTTON1_MASK,
            DND_TARGETS,
            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_MOVE)
        self.drag_dest_set(\
            gtk.DEST_DEFAULT_ALL,
            DND_TARGETS,
            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_MOVE)
        self.connect('drag_drop', self.on_drag_drop)
        self.connect('drag_data_get', self.on_drag_data_get)
        self.connect('drag_data_received', self.on_drag_data_received)
        #end of DnD initialization
        
        self.show()

    def get_columns(self):
        return self.columns.keys()

    def set_main_search_column(self,col_name):
        sort_nbr = self.columns[col_name][0]
        self.set_search_column(sort_nbr)

    def set_expander_column(self,col_name):
        col = self.columns[col_name][1]
        self.set_property("expander-column", col)

    def set_col_resizable(self,col_name,resizable):
        self.columns[col_name][1].set_resizable(resizable)

    def set_sort_column(self,col_name):
        if ENABLE_SORTING:
            self.treemodel.set_sort_column_id(self.columns[col_name][0],0)

    def set_col_visible(self,col_name,visible):
        self.columns[col_name][1].set_visible(visible)

    def set_bg_color(self,color_func,color_column):
        if self.columns.has_key(color_column):
            self.bg_color_column = self.columns[color_column][0]
            self.bg_color_func = color_func
        else:
            raise ValueError("There is no colum %s to use to set color"%color_column)


    #this is the GTK sorting function. It receive, as paramenter, a liblarch
    #sorting function which compares nid.
    def _sort_func(self, model, iter1, iter2, func=None):
        if model.iter_is_valid(iter1) and model.iter_is_valid(iter2):
            nid1 = model.get_value(iter1, 0)
            nid2 = model.get_value(iter2, 0)
            if nid1 and nid2 and func:
                id,order = self.treemodel.get_sort_column_id()
                node1 = self.basetree.get_node(nid1)
                node2 = self.basetree.get_node(nid2)
                sort = func(node1,node2,order)
            else:
                sort = -1
        else:
            print "some of the iter given for sorting are invalid. WTF?"
            sort = -1
        return sort


    def _celldatafunction(self, column, cell, model, iter):
        col = None
        if self.bg_color_func and self.bg_color_column:
            bgcolor = column.get_tree_view().get_style().base[gtk.STATE_NORMAL]
            if iter and model.iter_is_valid(iter):
                value = model.get_value(iter, self.bg_color_column)
                if value:
                    col = self.bg_color_func(value, bgcolor)
        cell.set_property("cell-background", col)

    def _separator_func(self, model, itera, user_data=None):
        if itera and model.iter_is_valid(itera):
            nid = model.get_value(itera, 0)
            node = self.basetree.get_node(nid)
            if self.separator_func:
                return self.separator_func(node)
            else:
                return False
        else:
            return False

    def set_row_separator_func(self,func):
        self.separator_func = func
        gtk.TreeView.set_row_separator_func(self,self._separator_func)

    def get_selected_nodes(self):
        ''' Return the selected nodes ID'''
        # Get the selection in the gtk.TreeView
        selection = self.get_selection()
        # Get the selection iter
        if selection.count_selected_rows() <= 0:
            ids = []
        else:
            model, paths = selection.get_selected_rows()
            iters = [model.get_iter(path) for path in paths]
            ts  = self.get_model()
            #0 is the column of the tid
            ids = [ts.get_value(iter, 0) for iter in iters]
        return ids
        
        
    ######### DRAG-N-DROP functions #####################################
    
    def on_drag_drop(self, treeview, context, selection, info, timestamp):
        self.emit_stop_by_name('drag_drop')

    def on_drag_data_get(self, treeview, context, selection, info, timestamp):
        """Extract data from the source of the DnD operation. Here the id of
        the parent task and the id of the selected task is passed to the
        destination"""
        treeselection = treeview.get_selection()
        model, paths = treeselection.get_selected_rows()
        iters = [model.get_iter(path) for path in paths]
        iter_str = ','.join([model.get_string_from_iter(iter) for iter in iters])
        selection.set('gtg/task-iter-str', 0, iter_str)
        return

    def on_drag_data_received(self, treeview, context, x, y, selection, info,\
                              timestamp):
        model          = treeview.get_model()
        drop_info = treeview.get_dest_row_at_pos(x, y)
        if drop_info:
            path, position = drop_info
            iter = model.get_iter(path)
            # Must add the task to the parent of the task situated\
            # before/after 
            if position == gtk.TREE_VIEW_DROP_BEFORE or\
               position == gtk.TREE_VIEW_DROP_AFTER:
                # Get sibling parent
                destination_iter = model.iter_parent(iter)
            else:
                # Must add task as a child of the dropped-on iter
                # Get parent
                destination_iter = iter
            if destination_iter:
                destination_tid = model.get_value(destination_iter, 0)
            else:
                #it means we have drag-n-dropped above the first task
                # we should consider the destination as a root then.
                destination_tid = None
        else:
            # Must add the task to the root
            # Parent = root => iter=None
            destination_tid = None

        # Get dragged iter as a TaskTreeModel iter
        iters = selection.data.split(',')
        for iter in iters:
            try:
                dragged_iter = model.get_iter_from_string(iter)
            except ValueError:
                #I hate to silently fail but we have no choice.
                #It means that the iter is not good.
                #Thanks shitty gtk API for not allowing us to test the string
                dragged_iter = None
            if dragged_iter and model.iter_is_valid(dragged_iter):
                dragged_tid = model.get_value(dragged_iter, 0)
                #TODO: it should be configurable for each TreeView if you want:
                # 0 : no drag-n-drop at all
                # 1 : drag-n-drop move the node
                # 2 : drag-n-drop copy the node 
                self.basetree.get_basetree().move_node(dragged_tid,\
                                                new_parent_id=destination_tid)
        self.emit_stop_by_name('drag_data_received')