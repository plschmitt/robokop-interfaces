from ftplib import FTP
from io import BytesIO
from json import loads
from gzip import decompress
from collections import defaultdict
from greent.graph_components import LabeledID
from greent.util import LoggingUtil
import logging

logger = LoggingUtil.init_logging(__name__, level=logging.DEBUG)

def pull_via_ftp(ftpsite, ftpdir, ftpfile):
    ftp = FTP(ftpsite)
    ftp.login()
    ftp.cwd(ftpdir)
    with BytesIO() as data:
        ftp.retrbinary(f'RETR {ftpfile}', data.write)
        binary = data.getvalue()
    ftp.quit()
    return binary

def pull_hgnc_json():
    """Get the HGNC json file & convert to python"""
    data = pull_via_ftp('ftp.ebi.ac.uk', '/pub/databases/genenames/new/json', 'hgnc_complete_set.json')
    hgnc_json = loads( data.decode() )
    return hgnc_json

def pull_uniprot_kb():
    data = pull_via_ftp('ftp.ebi.ac.uk','/pub/databases/uniprot/current_release/knowledgebase/idmapping/by_organism/', 'HUMAN_9606_idmapping.dat.gz')
    tabs = decompress(data).decode()
    return tabs

def json_2_identifiers(gene_dict):
    symbol = gene_dict['symbol']
    hgnc_id = LabeledID(identifier=gene_dict['hgnc_id'], label=symbol)
    idset = set([hgnc_id])
    if 'entrez_id' in gene_dict:
        idset.add( LabeledID(identifier=f"NCBIGENE:{gene_dict['entrez_id']}", label=symbol))
    if 'uniprot_ids' in gene_dict:
        idset.update([LabeledID(identifier=f"UniProtKB:{uniprotkbid}", label=symbol) for uniprotkbid in gene_dict['uniprot_ids']])
    if 'ensembl_gene_id' in gene_dict:
        idset.add( LabeledID(identifier=f"ENSEMBL:{gene_dict['ensembl_gene_id']}", label=symbol))
    return idset

def load_genes(rosetta):
    """The HGNC API limits users to 10 queries/second.  That's reasonable, but the data is pretty static.
    This function instead pulls the (not that big) data file from the server and puts the whole thing into the
    cache so that it will be found by subsequent synonymize calls.
    """
    ids_to_synonyms = synonymize_genes()
    for gene_id in ids_to_synonyms:
        key = f"synonymize({gene_id})"
        value = ids_to_synonyms[gene_id]
        rosetta.cache.set(key,value)
    logger.debug(f'Added {len(ids_to_synonyms)} gene symbols to the cache')

def synonymize_genes():
    """
    Our gene synonymization actually has to deal with UniProtKB ids as well, because they come back from GO. For a lot
    of them, they're not in HGNC.  So in our synonymizer, we go to uniprot, get the hgnc id, then go to hgnc. So
    we either need to make sure that doesn't happen, or look in the cache within the synonymizer.  I want to limit
    where we use the cache, so let's do that work up front.
    """
    ids_to_synonyms = {}
    hgnc = pull_hgnc_json()
    hgnc_genes = hgnc['response']['docs']
    logger.debug(f' Found {len(hgnc_genes)} genes in HGNC')
    hgnc_identifiers = [ json_2_identifiers(gene) for gene in hgnc_genes ]
    for idset in hgnc_identifiers:
        for lid in idset:
            ids_to_synonyms[lid.identifier] = idset

    tabs = pull_uniprot_kb()
    lines = tabs.split('\n')
    logger.debug(f'Found {len(lines)} lines in the uniprot data')
    uniprots = defaultdict(dict)
    for line in lines:
        x = line.split('\t')
        if len(x) < 3:
            continue
        uniprots[x[0]][x[1]] = x[2]
    premapped = 0
    isoforms = 0
    unpremapped = 0
    hgnc_mapped = 0
    entrez_mapped = 0
    still_unmapped = 0
    for up in uniprots:
        uniprot_id = f"UniProtKB:{up}"
        if uniprot_id in ids_to_synonyms:
            #great, we already know about this one
            premapped += 1
        elif '-' in up:
            isoforms += 1
        else:
            unpremapped += 1
            #Can we map it with HGNC?
            if ('HGNC' in uniprots[up]) and (uniprots[up]['HGNC'] in ids_to_synonyms):
                synonyms = ids_to_synonyms[uniprots[up]['HGNC']]
                synonyms.add(uniprot_id)
                ids_to_synonyms[uniprot_id] = synonyms
                hgnc_mapped += 1
            elif ('GeneID' in uniprots[up]) and (f"NCBIGENE:{uniprots[up]['GeneID']}" in ids_to_synonyms):
                #no? How about Entrez?
                entrez = f"NCBIGENE:{uniprots[up]['GeneID']}"
                synonyms = ids_to_synonyms[entrez]
                synonyms.add(uniprot_id)
                ids_to_synonyms[uniprot_id] = synonyms
                entrez_mapped += 1
            else:
                #Oh well.  There are a lot of other keys, but they don't overlap the HGNC Keys
                #We're still going to toss the uniprotkb in there, because, we're going to end up looking for
                # it later anyway
                still_unmapped += 1
                ids_to_synonyms[uniprot_id] = set([LabeledID(identifier=uniprot_id, label=None)])
    logger.debug(f'There were {premapped} UniProt Ids already mapped in HGNC')
    logger.debug(f'There were {isoforms} UniProt Ids that are just isoforms')
    logger.debug(f'There were {unpremapped} UniProt Ids not already mapped in HGNC')
    logger.debug(f'There were {hgnc_mapped} Mapped using HGNC notes in UniProt')
    logger.debug(f'There were {entrez_mapped} Mapped using Entrez in UniProt')
    logger.debug(f'There were {still_unmapped} UniProt Ids left that we are keeping as solos')
    return ids_to_synonyms

