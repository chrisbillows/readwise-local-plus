# Integrations

Generalised classes and functions that facilitate `workflows`.

Document here any useful information for enhancing those service interactions.

## Roam

Uses datomic queries.

### Anatomy of a datomic query

[
    :find                                          # REQUIRED
    ?my_var                                        # What we wanna find - what we will bind to the return value
    :in                                            # REQUIRED - or passing an arg separately to the query
    $                                              # STANDARD - query the whole db (probably required for Roam)
    ?target-uid                                    # Bind our passed arg(s) to a variable
    :where                                         # REQUIRED
        [                                          # -- DEFINE THE QUERY
            ?entities_meeting_the_criteria         # Bind entities (ids) matching criteria to a variable
            :block/uid                             # target entity-attribute i.e. fixed, real field names
            ?target-uid                            # The variable that our passed variable is bound to
        ]                                          # ---->  We now have an array of entities(ids) where attr = passed arg 
        [                                          # -- DEFINE THE OUTPUT
            ?entities_meeting_the_criteria         # Our arr of entities matching the query
            :block/string                          # Target entity attribute
            ?my_var                                # Bind the return values to our initial query parameter
        ]                     
]
"""

### Examples

#### `_query` endpoint

Use with the `_query` endpoint in Roam client.

```python
# get_all_pages
q = "[:find ?p ?title :where [?p :node/title ?title]]"

# get_all_pages_with_uid
q = "[:find ?p ?title ?uid :where [?p :node/title ?title][?p :block/uid ?uid]]"

# Return the 'block-text' of a given 'target-uid'
q = "[ :find ?block-text :in $ ?target-uid :where [?blocks :block/uid ?target-uid] [?blocks :block/string ?block-text]]"

# Return the 'block-text' of a given 'target-uid'
q = "[ :find ?page-title :in $ ?target-uid :where [?blocks :block/uid ?target-uid] [?blocks :node/title ?page-title]]"

# Return all attributes of an entity-id
q = "[:find ?e ?attr ?val :in $ ?uid :where [?e :block/uid ?uid] [?e ?attr ?val]]"
# {'result': [[235747, 'block/parents', 213878], [235747, 'edit/user', 234344], [235747, 'edit/time', 1755953526562], 
# [235747, 'block/string', 'Block added on Sat 23rd Aug'], [235747, 'block/open', True], [235747, 'block/page', 213878], 
# [235747, 'create/time', 1755953526562], [235747, 'block/order', 3], 
# [235747, 'block/uid', 'CRRAdcSIh'], [235747, 'create/user', 234344]]}

# General - can return any attribute above
q = "[ :find ?target-var :in $ ?target-uid :where [?blocks :block/uid ?target-uid] [?blocks :create/user ?target-var]]"

# Entity ID 
q = "[ :find ?attr ?val :in $ ?e :where [?e ?attr ?val] ]"

"""multi filter example - ENTITY first...  
[:find ?kid_name
 :in $ ?chris_uid
 :where
   [?chris :uid ?chris_uid]
   [?chris :person/child ?kid]
   [?kid :first_name ?kid_name]]
"""

# Parent of a block
q = (
        "[ :find ?parent-uid :in $ ?target-uid :where [?blocks :block/uid ?target-uid]" 
        "[?blocks :block/parents ?parents][?parents :node/title ?block-text]]"
)

# Text of af all immediate child blocks on a page
q = (
        "[ :find ?block-text :in $ ?target-uid :where" 
        "[?page :block/uid ?target-uid][?page :block/children ?children]"
        "[?children :block/string ?block-text]]"
)

# Get all text on a page recursive, pass rules as a second argument
q7= """[:find ?title ?descendant_uid ?descendant_text
         :in $ ?page_uid %
         :where
        [?page :block/uid ?page_uid]
        [?page :node/title ?title]
        (descendant ?page ?descendant)
        [?descendant :block/uid ?descendant_uid]
        [?descendant :block/string ?descendant_text]]"""
rules = """
        [
        [(descendant ?parent ?descendant)
        [?parent :block/children ?descendant]]
        [(descendant ?parent ?descendant)
        [?parent :block/children ?child]
        (descendant ?child ?descendant)]
        ]
        """
```

#### `_pull` endpoint

Use with `_pull` endpoint in Roam client.

```python
# all_block_attributes_and_children
q = {"eid": f'[:block/uid "{example_block_uid}"]', "selector": "[:* {:block/children [:*]}]"}
# all_block_attributes
q = {"eid": f'[:block/uid "{example_block_uid}"]', "selector": "[:*]"}
# page_name_or_block_text
q = {"eid": f'[:block/uid "{example_block_uid}"]', "selector": "[:block/uid :node/title :block/string]"}
```



