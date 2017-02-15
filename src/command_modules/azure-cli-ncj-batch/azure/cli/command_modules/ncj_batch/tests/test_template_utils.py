# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
import unittest

from azure.cli.command_modules.ncj_batch import _template_utils as utils


class TestBatchNCJTemplates(unittest.TestCase):
    # pylint: disable=attribute-defined-outside-init,no-member

    def setUp(self):
        data_dir = os.path.join(os.path.dirname(__file__), 'data')
        self.simple_job_template = os.path.join(data_dir, 'batch.job.simple.json')
        self.simple_pool_template = os.path.join(data_dir, 'batch.pool.simple.json')
        self.simple_job_parameters = os.path.join(data_dir, 'batch.job.parameters.json')
        self.simple_pool_parameters = os.path.join(data_dir, 'batch.job.parameters.json')
        return super(TestBatchNCJTemplates, self).setUp()

    def test_batch_ncj_expression_evaluation(self):
        # It should replace a string containing only an expression
        definition = {'value': "['evaluateMe']"}
        template = json.dumps(definition)
        parameters = {}
        result = utils._parse_template(template, definition, parameters)  # pylint:disable=protected-access
        self.assertEqual(result['value'], 'evaluateMe')

        # It should replace an expression within a string
        definition = {'value': "prequel ['alpha'] sequel"}
        template = json.dumps(definition)
        parameters = {}
        result = utils._parse_template(template, definition, parameters)  # pylint:disable=protected-access
        self.assertEqual(result['value'], 'prequel alpha sequel')

        # It should replace multiple expressions within a string
        definition = {'value': "prequel ['alpha'] interquel ['beta'] sequel"}
        template = json.dumps(definition)
        parameters = {}
        result = utils._parse_template(template, definition, parameters)  # pylint:disable=protected-access
        self.assertEqual(result['value'], 'prequel alpha interquel beta sequel')

        # It should unescape an escaped expression
        definition = {'value': "prequel [['alpha'] sequel"}
        template = json.dumps(definition)
        parameters = {}
        result = utils._parse_template(template, definition, parameters)  # pylint:disable=protected-access
        self.assertEqual(result['value'], "prequel ['alpha'] sequel")

        # It should not choke on JSON containing string arrays
        definition = {'values': ["alpha", "beta", "gamma", "[43]"]}
        template = json.dumps(definition)
        parameters = {}
        result = utils._parse_template(template, definition, parameters)  # pylint:disable=protected-access
        self.assertEqual(result['values'], ["alpha", "beta", "gamma", "43"])

        # It should not choke on JSON containing number arrays
        definition = {'values': [1, 1, 2, 3, 5, 8, 13]}
        template = json.dumps(definition)
        parameters = {}
        result = utils._parse_template(template, definition, parameters)  # pylint:disable=protected-access
        self.assertEqual(result['values'], [1, 1, 2, 3, 5, 8, 13])
