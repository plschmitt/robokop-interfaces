import argparse
import json
import os
import requests
import yaml
import shutil
from smartBag.grok import SemanticCrunch
from greent.rosetta import Rosetta
from greent import node_types
from greent.graph_components import KNode,KEdge,elements_to_json
from flask import Flask, jsonify, g, Response
from flasgger import Swagger
app = Flask(__name__)

template = {
  "swagger": "2.0",
  "info": {
    "title": "X-API",
    "description": "API for X data",
    "contact": {
      "responsibleOrganization": "x-org",
      "responsibleDeveloper": "x-dev",
      "email": "x@x.org",
      "url": "www.x.org",
    },
    "termsOfService": "http://x.org/terms",
    "version": "0.0.1"
  },
#  "host": "host.x",  # overrides localhost:500
#  "basePath": "/api",  # base bash for blueprint registration
  "schemes": [
    "http",
    "https"
  ]
}
app.config['SWAGGER'] = {
   'title': 'Rosetta Service',
   'bag_source' : '/.'
}

swagger = Swagger(app, template=template)

rosetta = None
def get_translator ():
   global rosetta
   if not rosetta:
      rosetta = Rosetta ()
   return rosetta

@app.route('/cop/')
def cop (drug="imatinib", disease="asthma"):
   """ Get service metadata 
   ---
   parameters:
     - name: drug
       in: path
       type: string
       required: false
       default: imatinib
       x-valueType:
         - http://schema.org/string
       x-requestTemplate:
         - valueType: http://schema.org/string
           template: /query?drug={{ input }}
     - name: disease
       in: path
       type: string
       required: false
       default: asthma
       x-valueType:
         - http://schema.org/string
       x-requestTemplate:
         - valueType: http://schema.org/string
           template: /query?disease={{ input }}
   responses:
     200:
       description: ...
   """
   print ("drug => {}".format (drug))
   print ("disease => {}".format (disease))
   blackboard = get_translator().graph (
      [ ( None, KNode('NAME.DISEASE:{0}'.format (disease), node_types.DISEASE_NAME) ) ],
      query=\
      """MATCH (d:disease),(b:gene), p = allShortestPaths((a)-[*]->(b)) 
      WHERE NONE (r IN relationships(p) WHERE type(r)='UNKNOWN') 
      RETURN p LIMIT 10""")
   blackboard += get_translator().graph (
      [ ( None, KNode('NAME.DRUG:{0}'.format (drug), node_types.DRUG_NAME) ) ],
      query=\
      """MATCH (a{name:"NAME.DRUG"}),(b:pathway), p = allShortestPaths((a)-[*]->(b)) 
      WHERE NONE (r IN relationships(p) WHERE type(r)='UNKNOWN') 
      RETURN p LIMIT 10""")
   result = [ elements_to_json (e) for e in blackboard ]
   return jsonify (result)
    
@app.route('/smartbag/compile/<bag_url>/')
def smartbag_compile (bag_url):
   """ Given a smartBag URL, fetch the bag and compile it to a smartAPI.
   ---
   parameters:
     - name: bag_url
       in: path
       type: string
       required: true
       x-valueType:
         - http://schema.org/url
       x-requestTemplate:
         - valueType: http://schema.org/url
           template: /url={{ bag_url }}
   responses:
     200:
       x-responseValueType:
         - path: x.y.z
           valueType: http://x.y/z
       x-JSONLDContext: /x.jsonld
   """
   bag_source = app.config['SWAGGER']['bag_source']
   bag_url = f"{bag_source}/{bag_url}"
   print (bag_url)
   bag_archive_file = bag_url.split ("/")[-1]
   print (f"bag archive: {bag_archive_file}")
   
   bag_base_name = bag_archive_file.replace (".tgz", "").replace (".zip", "")
   out_dir = os.path.join ("smartbag", "work", bag_base_name)
   if os.path.exists (out_dir):
      shutil.rmtree (out_dir)
   os.makedirs (out_dir)
   bag_archive_file_fq = os.path.join (out_dir, bag_archive_file)
   if bag_url.startswith ("http"):
      r = requests.get (bag_url, stream=True)
      with open(bag_archive_file_fq, 'wb') as outf:
         for chunk in r.iter_content(chunk_size=1024):
            if chunk:  # filter out keep-alive new chunks
               outf.write(chunk)
   else:
      shutil.copyfile (bag_url, bag_archive_file_fq)
   manifest = SemanticCrunch.generate_smartapi(
      bag=bag_archive_file_fq,
      output_dir=out_dir,
      title="TODO-Title")
   return jsonify(manifest)

if __name__ == "__main__":
   print ("""
      ____                         __    __                
     / __ \  ____    _____  ___   / /_  / /_  ____ _       
    / /_/ / / __ \  / ___/ / _ \ / __/ / __/ / __ `/       
   / _, _/ / /_/ / (__  ) /  __// /_  / /_  / /_/ /        version 0.0.1
  /_/ |_|  \____/ /____/  \___/ \__/  \__/  \__,_/  
      
   """)                                                  
   parser = argparse.ArgumentParser(description='Rosetta Server')
   parser.add_argument('-s', '--bag-source', help='Filesystem path or URL serving bags.', default='.')
   parser.add_argument('-p', '--port', type=int, help='Port to run service on.', default=None)
   args = parser.parse_args ()
   app.config['SWAGGER']['bag_source'] = args.bag_source
   app.run(host='0.0.0.0', port=args.port, debug=True, threaded=True)