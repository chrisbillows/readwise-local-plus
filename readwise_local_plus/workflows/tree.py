import uuid

class Node:
    def __init__(self, type_, data):
        self.id = str(uuid.uuid3)
        self.type = type_
        self.data = data
        self.children = []
        self.parent = None

    def add_child(self, child):
        child.parent = self
        self.children.append(child)

def get_children(node):
    return node.children

def get_parent(node):
    return node.parent

def get_siblings(node):
    if not node.parent:
        return []
    return [c for c in node.parent.children if c != node]
