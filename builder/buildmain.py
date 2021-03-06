from greent import node_types
from greent.util import LoggingUtil,Text
from greent.rosetta import Rosetta
from greent.export import BufferedWriter
from builder.userquery import UserQuery
import argparse
import logging
import sys
from importlib import import_module
from builder.lookup_utils import lookup_identifier
from collections import defaultdict, deque
from builder.pathlex import tokenize_path
from builder.question import Question
import datetime

logger = LoggingUtil.init_logging(__name__, logging.INFO)

def run_query(querylist, supports, rosetta, prune=False):
    """Given a query, create a knowledge graph though querying external data sources.  Export the graph"""
    # kgraph = KnowledgeGraph(querylist, rosetta)
    if not querylist.compile_query(rosetta):
        raise RuntimeError('Query fails. Exiting.')

    # kgraph.execute()
    logger.debug('Executing Query')
    logger.debug('Run Programs')
    for program in querylist.get_programs():
        result_graph = program.run_program()
    logger.debug('Query Complete')


def generate_query(pathway, start_identifiers, start_name = None, end_identifiers=None, end_name=None):
    start, middle, end = pathway[0], pathway[1:-1], pathway[-1]
    query = UserQuery(start_identifiers, start.nodetype, start_name)
    for transition in middle:
        print(transition)
        query.add_transition(transition.nodetype, transition.min_path_length, transition.max_path_length)
    query.add_transition(end.nodetype, end.min_path_length, end.max_path_length, end_values=end_identifiers, end_name=end_name)
    return query


conceptsAndIds = [
  ("anatomical_entity", "A"),
  ("biological_process_or_activity", "P"),
  ("cell", "C"),
  ("chemical_substance", "S"),
  ("disease", "D"),
  ("gene", "G"),
  ("phenotypic_feature", "T"),
  ("genetic_condition", "X")
]
map = {c[1]:c[0] for c in conceptsAndIds}

def build_spec(spec_sequence, start_name, start_id, end_name=None, end_id=None):
    sequence_ids = [map[c] for c in spec_sequence]
    
    machine_question = {'nodes': [], 'edges': []}
    node, edge = build_step(sequence_ids[0], start_name, start_id, id=0)
    machine_question['nodes'].append(node)
    if edge:
        machine_question['edges'].append(edge)
    for idx, s in enumerate(sequence_ids[1:-1]):
        node, edge = build_step(s, id=idx+1)
        machine_question['nodes'].append(node)
        machine_question['edges'].append(edge)
    if end_name:
        node, edge = build_step(sequence_ids[-1], end_name, end_id, id=len(sequence_ids)-1)
        machine_question['nodes'].append(node)
        machine_question['edges'].append(edge)

        sequence_name = ' -> '.join(sequence_ids[1:-1])
        name = f'{start_name} -> {sequence_name} -> {end_name}'
        natural = f'{spec_sequence}({start_name}, {end_name})'
        
    else:
        node, edge = build_step(sequence_ids[-1], id=len(sequence_ids)-1)
        machine_question['nodes'].append(node)
        machine_question['edges'].append(edge)
        
        sequence_name = ' -> '.join(sequence_ids[1:])
        name = f'{start_name} -> {sequence_name}'
        natural = f'{spec_sequence}({start_name})'

    out = {"name": name,
           "natural_question": natural, 
           "notes": '',
           "machine_question": machine_question
    }
    return out

def build_step(spec, name=None, curie=None, id=0):
    if name and curie:
        node = {
            "type": spec,
            "name": name,
            "curie": curie,
            "id": id
        }
    else:
        node = {
            "type": spec,
            "id": id
        }
    if id:
        edge = {
            "source_id": id-1,
            "target_id": id
        }
    else:
        edge = None
    return node, edge

def run(pathway, start_name, start_id, end_name, end_id, supports, config):
    """Programmatic interface.  Pathway defined as in the command-line input.
       Arguments:
         pathway: A string defining the query.  See command line help for details
         start_name: The name of the entity at one end of the query
         end_name: The name of the entity at the other end of the query. Can be None.
         label: the label designating the result in neo4j
         supports: array strings designating support modules to apply
         config: Rosettta environment configuration. 
    """
    spec = build_spec(pathway, start_name, start_id, end_name=end_name, end_id=end_id)
    q = Question(spec)

    rosetta = setup(config)
    programs = q.compile(rosetta)

    for p in programs:
        p.run_program()


def setup(config):
    logger = logging.getLogger('application')
    logger.setLevel(level=logging.DEBUG)
    rosetta = Rosetta(greentConf=config,debug=True)
    return rosetta


helpstring = """Execute a query across all configured data sources.  The query is defined 
using the -p argument, which takes a string.  Each character in the string 
represents one high-level type of node that will be sequentially included 
denoted as:
S: Substance (Drug)
G: Gene
P: Process (Pathway)
C: Cell Type
A: Anatomical Feature
T: Phenotype
D: Disease
X: Genetic Condition
?: Unspecified Node

It is also possible to specify indirect transitions by including 
parenthetical values between these letters containing the number of 
allowed type transitions. A default (direct) transition would
be denoted (1-1), but it is not necessary to include between
every node.

Examples:
    DGX        Go directly from Disease, to Gene, to Genetic Condition.
    D(1-2)X    Go from Disease to Genetic Condition, either directly (1)
               or via another node (of any type) in between
    SGPCATD    Construct a Clinical Outcome Pathway, moving from a Drug 
               to a Gene to a Process to a Cell Type to an Anatomical 
               Feature to a Phenotype to a Disease. Each with no 
               intermediary nodes
    SG(2-5)D   Go from a Drug to a Gene, through 2 to 5 other transitions, and 
               to a Disease.
"""


def main():
    parser = argparse.ArgumentParser(description=helpstring,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-s', '--support', help='Name of the support system',
                        action='append',
                        #choices=['chemotext', 'chemotext2', 'cdw'],
                        choices=['omnicorp', 'chemotext', 'cdw'],
                        required=True)
    parser.add_argument('-p', '--pathway', help='Defines the query pathway (see description). Cannot be used with -q',
                        required=False)
    parser.add_argument('-q', '--question',
                        help='Shortcut for certain questions (1=Disease/GeneticCondition, 2=COP, 3=COP ending in Phenotype). Cannot be used with -p',
                        choices=[1, 2, 3],
                        required=False,
                        type=int)
    parser.add_argument('-c', '--config', help='Rosetta environment configuration file.',
                        default='greent.conf')
    parser.add_argument('--start', help='Text to initiate query', required=True)
    parser.add_argument('--end', help='Text to finalize query', required=False)
    parser.add_argument('--start_id', help='Text to initiate query', required=True)
    parser.add_argument('--end_id', help='Text to finalize query', required=False)
    args = parser.parse_args()
    pathway = None
    if args.pathway is not None and args.question is not None:
        print('Cannot specify both question and pathway. Exiting.')
        sys.exit(1)
    if args.question is not None:
        if args.question == 1:
            pathway = 'DGX'
            if args.end is not None:
                print('--end argument not supported for question 1.  Ignoring')
        elif args.question == 2:
            pathway = 'SGPCATD'
        elif args.question == 3:
            pathway = 'SGPCAT'
        if args.question in (2, 3):
            if args.end is None:
                print('--end required for question 2. Exiting')
                sys.exit(1)
    else:
        pathway = args.pathway
    run(pathway, args.start, args.start_id, args.end, args.end_id, args.support, config=args.config)


if __name__ == '__main__':
    main()
