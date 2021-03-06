#!/usr/bin/env python

"""Flask REST API server for builder"""

import os
import json
import requests
import logging

import redis
from flask import request
from flask_restful import Resource, reqparse

from builder.api.setup import app, api
from builder.api.tasks import update_kg
import builder.api.logging_config
import greent.node_types as node_types
import builder.api.definitions

class UpdateKG(Resource):
    def post(self):
        """
        Update the cached knowledge graph 
        ---
        tags: [build]
        parameters:
          - in: body
            name: question
            description: The machine-readable question graph.
            schema:
                $ref: '#/definitions/Question'
            required: true
        responses:
            202:
                description: Update started...
                schema:
                    type: object
                    required:
                      - task id
                    properties:
                        task id:
                            type: string
                            description: task ID to poll for KG update status
        """
        # replace `parameters`` with this when OAS 3.0 is fully supported by Swagger UI
        # https://github.com/swagger-api/swagger-ui/issues/3641
        """
        requestBody:
            description: The machine-readable question graph.
            required: true
            content:
                application/json:
                    schema:
                        $ref: '#/definitions/Question'
        """
        logger = logging.getLogger('builder')
        logger.info("Queueing 'KG update' task...")
        task = update_kg.apply_async(args=[request.json])
        return {'task id': task.id}, 202

api.add_resource(UpdateKG, '/')

class TaskStatus(Resource):
    def get(self, task_id):
        """
        Get the status of a task
        ---
        tags: [tasks]
        parameters:
          - in: path
            name: task_id
            description: ID of the task
            type: string
            required: true
        responses:
            200:
                description: Task status
                schema:
                    type: object
                    required:
                      - task-id
                      - state
                      - result
                    properties:
                        task_id:
                            type: string
                        status:
                            type: string
                            description: Short task status
                        result:
                            type: ???
                            description: Result of completed task OR intermediate status message
                        traceback:
                            type: string
                            description: Traceback, in case of task failure
        """

        r = redis.Redis(
            host=os.environ['RESULTS_HOST'],
            port=os.environ['RESULTS_PORT'],
            db=os.environ['BUILDER_RESULTS_DB'])
        value = r.get(f'celery-task-meta-{task_id}')
        if value is None:
            return 'Task not found', 404
        result = json.loads(value)
        return result, 200

api.add_resource(TaskStatus, '/task/<task_id>')

class Concepts(Resource):
    def get(self):
        """
        Get known biomedical concepts
        ---
        tags: [util]
        responses:
            200:
                description: Concepts
                schema:
                    type: array
                    items:
                        type: string
        """
        concepts = list(node_types.node_types - {'UnspecifiedType'})
        return concepts

api.add_resource(Concepts, '/concepts')

if __name__ == '__main__':

    # Get host and port from environmental variables
    server_host = '0.0.0.0' #os.environ['ROBOKOP_HOST']
    server_port = int(os.environ['BUILDER_PORT'])

    app.run(host=server_host,\
        port=server_port,\
        debug=True,\
        use_reloader=True)
