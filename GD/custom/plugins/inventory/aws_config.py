from __future__ import absolute_import, division, print_function

__metaclass__ = type
#PLUGIN VARS
#iam_role_arn: needs to be a role that plugin can assume in master account to access config aggregator. - used by plugin for collecting inventory data
#aggregator_name: the name of the config aggregator to query
#configquery: the SQL query to send to the AWS Config Aggregator
#configregion: The region the config aggregator is in
#configaccountid: The account id that contains the config aggregator

#INVENTORY VARS
#ansible_aws_ssm_bucket_name: "cm-$awsregion" - used by session manager
#ansible_aws_ssm_profile: "$accountid-$awsregion" - used by session manager
#ansible_aws_ssm_region: "$awsregion" - used by session manager
#ansible_connection: community.aws.aws_ssm - used by session manager
#ansible_shell_type: if platform is windows then 'powershell' - used by session manager
#ansible_python_interpreter: if platform is linux then "/usr/bin/python3" - used by session manager

DOCUMENTATION = """
name: aws_config
short_description: AWS Config instance inventory source
description:
  - Get instances from Amazon Web Services Config Service.
  - Uses a YAML configuration file that ends with aws_config.(yml|yaml).
options:
  aws_profile:
    description:
      - The awscli profile used to connect to the Config API
  region:
    description:
      - A list of regions in which to describe instances and clusters. Available regions are listed here
        U(https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.RegionsAndAvailabilityZones.html).
    default: []
  aggregator_name:
    description:
      - The name of the AWS Config aggregator you wish to query for instances
    type: str
  strict_permissions:
    description:
      - By default if an AccessDenied exception is encountered this plugin will fail. You can set strict_permissions to
        False in the inventory config file which will allow the restrictions to be gracefully skipped.
    type: bool
    default: True
  include_clusters:
    description: Whether or not to query for Aurora clusters as well as instances.
    type: bool
    default: False
  statuses:
    description: A list of desired states for instances/clusters to be added to inventory. Set to ['all'] as a shorthand to find everything.
    type: list
    elements: str
    default:
      - creating
      - available
  iam_role_arn:
    description:
      - The ARN of the IAM role to assume to perform the inventory lookup. You should still provide
        AWS credentials with enough privilege to perform the AssumeRole action.
  hostvars_prefix:
    description:
      - The prefix for host variables names coming from AWS.
    type: str
    version_added: 3.1.0
  hostvars_suffix:
    description:
      - The suffix for host variables names coming from AWS.
    type: str
    version_added: 3.1.0
notes:
  - Ansible versions prior to 2.10 should use the fully qualified plugin name 'amazon.aws.aws_rds'.
extends_documentation_fragment:
  - inventory_cache
  - constructed
  - amazon.aws.aws_boto3
  - amazon.aws.aws_credentials
author:
  - Sloane Hertel (@s-hertel)
"""

EXAMPLES = """
plugin: aws_rds
regions:
  - us-east-1
  - ca-central-1
keyed_groups:
  - key: 'db_parameter_groups|json_query("[].db_parameter_group_name")'
    prefix: rds_parameter_group
  - key: engine
    prefix: rds
  - key: tags
  - key: region
hostvars_prefix: aws_
hostvars_suffix: _rds
"""

try:
    import boto3
    import botocore
    import json
    import ast
    import pdb
except ImportError:
    pass  # will be captured by imported HAS_BOTO3

from ansible.errors import AnsibleError
from ansible.module_utils._text import to_native
from ansible.plugins.inventory import BaseInventoryPlugin
from ansible.plugins.inventory import Cacheable
from ansible.plugins.inventory import Constructable

from ansible_collections.amazon.aws.plugins.module_utils.core import is_boto3_error_code
from ansible_collections.amazon.aws.plugins.module_utils.ec2 import HAS_BOTO3
from ansible_collections.amazon.aws.plugins.module_utils.ec2 import (
    ansible_dict_to_boto3_filter_list,
)
from ansible_collections.amazon.aws.plugins.module_utils.ec2 import (
    boto3_tag_list_to_ansible_dict,
)
from ansible_collections.amazon.aws.plugins.module_utils.ec2 import (
    camel_dict_to_snake_dict,
)


class InventoryModule(BaseInventoryPlugin):

    NAME = "aws_config"

    def verify_file(self, path):
        """
        :param loader: an ansible.parsing.dataloader.DataLoader object
        :param path: the path to the inventory config file
        :return the contents of the config file
        """
        if super(InventoryModule, self).verify_file(path):
            if path.endswith(("aws_config.yml", "aws_config.yaml")):
                return True
        return False

    def parse(self, inventory, loader, path, cache=True):
        super(InventoryModule, self).parse(inventory, loader, path)

        if not HAS_BOTO3:
            raise AnsibleError(
                "The AWS Config dynamic inventory plugin requires boto3 and botocore."
            )

        # get user specifications from yml config
        self._read_config_data(path)
        self.region = self.get_option('region')
        self.aggregator_name = self.get_option('aggregator_name')

        # Generate inventory
        all_instances = []

        awsconfig = boto3.client('config')

        self.configquery = """
        SELECT 
            resourceId,
            accountId,
            awsRegion,
            configuration.state.name,
            configuration.instanceType,
            configuration.publicDnsName,
            configuration.privateIpAddress,
            configuration.privateDnsName,
            configuration.platform,
            availabilityZone,
            tags.tag,
            tags.value,
            tags.key
        WHERE 
            resourceType = 'AWS::EC2::Instance'
        """

        resp = awsconfig.select_aggregate_resource_config(
            Expression=self.configquery,
            ConfigurationAggregatorName=self.aggregator_name,
            Limit=100,
        )
        all_instances.extend(resp["Results"])

        while "NextToken" in resp:
            resp = awsconfig.select_aggregate_resource_config(
                Expression=self.configquery,
                ConfigurationAggregatorName=self.aggregator_name,
                Limit=100,
                NextToken=resp["NextToken"],
            )
            all_instances.extend(resp["Results"])
        
        all_instances = [ast.literal_eval('{%s}' % item[1:-1]) for item in all_instances]

        #Create groups for each account ID, platform, region, and state
        #Platform is blank for Linux systems, so we prepopulate the groups with a linux value and put blank platforms into that group
        groups = ["linux"]

        for instance in all_instances:

          if not instance['accountId'] in groups:
            groups.append(instance['accountId'])
          if "platform" in instance['configuration'] and not instance['configuration']['platform'] in groups:
            groups.append(instance['configuration']['platform'])
          if not instance['configuration']['state']['name'] in groups:
            groups.append(instance['configuration']['state']['name'])
          if not instance['awsRegion'].replace("-","_") in groups:
            groups.append(instance['awsRegion'].replace("-","_"))
        
        for group in groups:
          self.inventory.add_group(group)
        
        #pdb.set_trace()
        
        #Add hosts to the inventory, set groups, and set host variables
        for instance in all_instances:
            self.inventory.add_host(instance["resourceId"])
            self.inventory.set_variable(
                instance["resourceId"], "ansible_host", instance["resourceId"]
            )
            self.inventory.add_host(
              instance["resourceId"], group = instance["accountId"]
            )
            self.inventory.add_host(
              instance["resourceId"], group = instance["awsRegion"].replace("-","_")
            )
            self.inventory.add_host(
              instance["resourceId"], group = instance['configuration']['state']['name']
            )
            if "platform" in instance['configuration']:
              self.inventory.add_host(
                instance["resourceId"], group = instance['configuration']['platform']
              )
            else:
              self.inventory.add_host(
                instance["resourceId"], group = "linux"
              )
            
            


