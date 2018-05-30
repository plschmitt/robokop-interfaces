import asyncio
import concurrent.futures
import requests
import json
import logging
import sys
import os
import traceback
from datetime import datetime as dt
from collections import defaultdict
from collections import namedtuple
from csv import DictReader
from greent.util import Munge
from greent.util import Text
from greent.service import Service
from greent.util import LoggingUtil
from greent.async import AsyncUtil
from greent.async import Operation
from greent.graph_components import KEdge, KNode, LabeledID
from greent import node_types
from simplejson.scanner import JSONDecodeError

logger = LoggingUtil.init_logging(__name__, logging.DEBUG)


class Pharos(Service):
    def __init__(self, context):
        super(Pharos, self).__init__("pharos", context)

    def request(self, url):
        response = None
        try:
            response = requests.get(url).json()
        except:
            traceback.print_exc()
        return response

    def query(self, query):
        return self.request("{0}/{1}".format(self.url, query))

    def target_to_id(self, target):
        target_map = self.query(query="targets/{0}".format(Munge.gene(target)))
        return target_map["id"] if "id" in target_map else None

    def target_to_disease(self, target_sym):
        target_id = self.target_to_id(Munge.gene(target_sym))
        links = self.query(query="targets({0})/links".format(target_id))
        result = []
        for k in links:
            if k['kind'] == "ix.idg.models.Disease":
                for p in k['properties']:
                    # print (p)
                    if p['label'] == 'IDG Disease':
                        result.append(p['term'])
        return result

    def disease_map(self, disease_id):
        return self.query(query="diseases({0})".format(disease_id))

    def make_doid_id(self, obj):
        if not obj:
            return None
        result = obj
        if isinstance(obj, KNode):
            result = obj.identifier
        if isinstance(result, list):
            if len(result) == 1:
                result = result[0]
        if result:
            if isinstance(result, str):
                if result.startswith('DOID:'):
                    result = result.replace('DOID:', '')
        return result

    def translate(self, subject_node):
        """Convert a subject with a DOID or UMLS into a Pharos Disease ID"""
        # TODO: This relies on a pretty ridiculous caching of a map between pharos ids and doids.
        #      As Pharos improves, this will not be required, but for the moment I don't know a better way.
        pmap = defaultdict(list)
        print (f"-------------------- {subject_node}")
        pharos_id_filename = os.path.join(os.path.dirname(__file__), 'pharos.id.all.txt')
        with open(pharos_id_filename, 'r') as inf:
            rows = DictReader(inf, dialect='excel-tab')
            for row in rows:
                if row['DOID'] != '':
                    doidlist = row['DOID'].split(',')
                    for d in doidlist:
                        pmap[d.upper()].append(row['PharosID'])
        valid_identifiers = subject_node.get_synonyms_by_prefix('DOID')
        valid_identifiers.update(subject_node.get_synonyms_by_prefix('UMLS'))
        pharos_set = set()
        for vi in valid_identifiers:
            pharos_set.update(pmap[vi])
        pharos_list = list(pharos_set)
        return pharos_list

    def target_to_hgnc(self, target_id):
        """Convert a pharos target id into an HGNC ID.
        The call does not return the actual name for the gene, so we do not provide it.
        There are numerous other synonyms that we could also cache, but I don't see much benefit here. """
        result = None
        try:
            r = requests.get('https://pharos.nih.gov/idg/api/v1/targets(%s)/synonyms' % target_id)
            result = r.json()
            for synonym in result:
                if synonym['label'] == 'HGNC':
                    result = synonym['term']
        except:
            pass
        return result

    def drugname_string_to_pharos_info(self, drugname):
        """Exposed for use in name lookups without KNodes"""
        r = requests.get('https://pharos.nih.gov/idg/api/v1/ligands/search?q={}'.format(drugname)).json()
        return_results = set()
        foundany = False
        for contents in r['content']:
            foundany=True
            synonym_href = contents['_synonyms']['href']
            sres = requests.get(synonym_href).json()
            for syno in sres:
                if syno['href'].startswith('https://www.ebi.ac.uk/chembl/compound/inspect/'):
                    term = syno['href'].split('/')[-1]
                    identifier = 'CHEMBL:{}'.format(term)
                    return_results.add( (identifier, drugname) )
        if foundany and len(return_results) == 0:
            print('UHOH')
            print(drugname)
            exit()
        return list(return_results)

    def drugname_to_pharos(self, namenode):
        drugname = Text.un_curie(namenode.identifier)
        pharosids = self.drugname_string_to_pharos_info(drugname)
        results = []
        predicate = LabeledID('RDFS:id', 'identifies')
        for pharosid, pharoslabel in pharosids:
            newnode = KNode(pharosid, node_types.DRUG, label=pharoslabel)
            newedge = KEdge(namenode, newnode, 'pharos.drugname_to_pharos', namenode.identifier, predicate)
            results.append((newedge, newnode))
        return results

    def drugid_to_identifiers(self,refid):
        url = 'https://pharos.nih.gov/idg/api/v1/ligands(%s)/synonyms' % refid
        result = requests.get(url).json()
        chemblid = None
        label = None
        for element in result:
            if element['label'] == 'IDG Drug':
                label = element['term']
            if element['label'] == 'CHEMBL ID':
                chemblid = f"CHEMBL:{element['term']}"
        return chemblid, label

    def gene_get_drug(self, gene_node):
        """ Get a drug from a gene. """
        resolved_edge_nodes = []
        identifiers = gene_node.get_synonyms_by_prefix('UNIPROTKB')
        for s in identifiers:
            try:
                pharosid = Text.un_curie(s)
                original_edge_nodes = []
                url = 'https://pharos.nih.gov/idg/api/v1/targets(%s)?view=full' % pharosid
                r = requests.get(url)
                try:
                    result = r.json()
                except:
                    #If pharos doesn't know the identifier, it just 404s.  move to the next
                    continue 
                actions = set()  # for testing
                predicate = LabeledID('PHAROS:drug_targets','is_target')
                chembl_id = None
                for link in result['links']:
                    if link['kind'] == 'ix.idg.models.Ligand':
                        pharos_drug_id = link['refid']
                        chembl_id, label = self.drugid_to_identifiers(pharos_drug_id)
                        if chembl_id is not None:
                            drug_node = KNode(chembl_id, node_types.DRUG,label=label)
                            edge = self.create_edge(drug_node,gene_node, 'pharos.gene_get_drug',
                                    pharosid,predicate, url=url)
                            resolved_edge_nodes.append( (edge,drug_node) )
            except:
                logger.debug("Error encountered calling pharos with",s)
        return resolved_edge_nodes


    def drug_get_gene(self, subject):
        """ Get a gene from a drug. """
        resolved_edge_nodes = []
        identifiers = subject.get_synonyms_by_prefix('CHEMBL')
        for s in identifiers:
            pharosid = Text.un_curie(s)
            original_edge_nodes = []
            url = 'https://pharos.nih.gov/idg/api/v1/ligands(%s)?view=full' % pharosid
            r = requests.get(url)
            try: 
                result = r.json()
            except:
                #Pharos returns a 404 if it doesn't recognize the identifier, which ends up producing
                # errors in turning into json. Skip to next identifier
                continue
            actions = set()  # for testing
            predicate = LabeledID('PHAROS:drug_targets','is_target')
            for link in result['links']:
                if link['kind'] == 'ix.idg.models.Target':
                    pharos_target_id = int(link['refid'])
                    hgnc = self.target_to_hgnc(pharos_target_id)
                    if hgnc is not None:
                        hgnc_node = KNode(hgnc, node_types.GENE)
                        edge = self.create_edge(subject,hgnc_node,'pharos.drug_get_gene',pharosid,predicate,url=url)
                        resolved_edge_nodes.append((edge, hgnc_node))
                    else:
                        logging.getLogger('application').warn('Did not get HGNC for pharosID %d' % pharos_target_id)
        return resolved_edge_nodes

    def disease_get_gene(self, subject):
        """ Get a gene from a pharos disease id. """
        pharos_ids = self.translate(subject)
        resolved_edge_nodes = []
        for pharosid in pharos_ids:
            logging.getLogger('application').debug("Identifier:" + subject.identifier)
            original_edge_nodes = []
            url='https://pharos.nih.gov/idg/api/v1/diseases(%s)?view=full' % pharosid
            r = requests.get(url)
            result = r.json()
            predicate=LabeledID('PHAROS:gene_involved','gene_involved')
            for link in result['links']:
                if link['kind'] == 'ix.idg.models.Target':
                    pharos_target_id = int(link['refid'])
                    hgnc = self.target_to_hgnc(pharos_target_id)
                    if hgnc is not None:
                        hgnc_node = KNode(hgnc, node_types.GENE)
                        edge = self.create_edge(subject,hgnc_node,'pharos.disease_get_gene',pharosid,predicate,url=url)
                        resolved_edge_nodes.append((edge, hgnc_node))
                    else:
                        logging.getLogger('application').warn('Did not get HGNC for pharosID %d' % pharos_target_id)
            return resolved_edge_nodes


