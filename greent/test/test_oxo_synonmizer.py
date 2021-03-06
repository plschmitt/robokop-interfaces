from greent.graph_components import KNode
from greent.synonymizers.oxo_synonymizer import synonymize
from greent.conftest import rosetta
from greent import node_types

def test_neuron(rosetta):
    node = KNode("CL:0000540", type=node_types.CELL)
    synonymize(node,rosetta.core)
    assert len(node.synonyms) >  10
    #we're no longer so pathological about trying to get meshIDs so in this case we don't get one
    meshcell = node.get_synonyms_by_prefix("MESH")
    assert len(meshcell) == 0
    #BUt we should get a UMLS
    umlscell = node.get_synonyms_by_prefix("UMLS")
    mid = list(umlscell)[0]
    assert mid == 'UMLS:C0027882' \

def test_phenotype(rosetta):
    node = KNode("MEDDRA:10014408", type=node_types.PHENOTYPE)
    synonymize(node,rosetta.core)
    assert len(node.synonyms) >  10
    hpsyns = node.get_synonyms_by_prefix("HP")
    assert len(hpsyns) > 0
    print(hpsyns)

def test_names(rosetta):
    node = KNode('HP:0002527', type=node_types.PHENOTYPE, name='Falls')
    synonymize(node,rosetta.core)
    print( node.synonyms )
    msyns = node.get_labeled_ids_by_prefix("MedDRA")
    assert len(msyns) == 1
    ms = msyns.pop()
    assert ms.identifier == 'MedDRA:10016173'
    assert ms.label == 'Fall'

