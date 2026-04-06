import uuid
from random import randint

class Node:
    def __init__(self, type_, data, parent_uid):
        # self.id: str = str(uuid.uuid1()) 
        self.id = randint(1000, 9999)
        self.type = type_
        self.data = data
        self.parent_uid
        self.children = []

    def add_child(self, child):
        child.parent = self
        self.children.append(child)

    def __repr__(self):
        node_repr = {}
        node_repr['id'] = self.id
        node_repr['type'] = self.type
        node_repr['data'] = self.data
        node_repr['children'] = {}
        
        # def foo(node_repr, node):
        #     pass
        s = f"Node: id={self.id} type={self.type} data={self.data[:30]}"
        return s

def get_children(node):
    return node.children

def get_parent(node):
    return node.parent

def get_siblings(node):
    if not node.parent:
        return []
    return [c for c in node.parent.children if c != node]
