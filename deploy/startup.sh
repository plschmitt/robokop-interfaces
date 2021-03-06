#!/bin/bash
### every exit != 0 fails the script
set -e

chown -R murphy:murphy $ROBOKOP_HOME

cd $ROBOKOP_HOME/robokop-interfaces
source ./deploy/setenv.sh

# set up Neo4j type graph
./initialize_type_graph.sh

find . -name "*.pid" -exec rm -rf {} \;

cd - > /dev/null # squash output
exec "$@"