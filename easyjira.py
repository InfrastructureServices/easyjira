#!/usr/bin/env python3

import argparse
import os
import requests
import sys
import codecs # for decoding escape characters
import urllib
import pprint
import json
import textwrap
import getpass
import re

currentdir = os.path.dirname(os.path.realpath(__file__))
fake_data_dir = currentdir + '/tests'

class FakeResponse:
    def __init__(self, text):
        self.text = text
    def ok(self):
        return True
    def json(self):
        return self.text

class EasyJira:
    def __init__(self):
        self.program_name = 'easyjira'
        self.JIRA_PROJECTS_URL = "https://issues.redhat.com"
        self.JIRA_REST_URL = f"{self.JIRA_PROJECTS_URL}/rest/api/2"
        self.DEFAULT_MAX_RESULTS = 20
        self._token_path = os.path.expanduser("~/.config/jira/" + self.program_name)
        self._token = None
        self._program_args = None
        self._default_output = "{key}"
        self._log_headers_done = False
        self._debug = False

        self.link_data = {
            "clones": {
              "name": "Cloners",
              "inward":"is cloned by",
              "outward":"clones"
              },
            "blocks": {
              "name": "Blocks",
              "inward": "is blocked by",
              "outward": "blocks",
              },
            "depends on": {
              "name": "Depend",
              "inward": "is depended on by",
              "outward": "depends on",
              },
            "duplicates": {
              "name": "Duplicate",
              "inward": "is duplicated by",
              "outward": "duplicates",
              }
            }

    def _error(self, message):
        print(f'ERROR: {message}')
        exit(1)


    def _debug_print(self, message):
        if self._debug:
            print(message)


    def _get_token(self) -> str:
        """Retrieves the JIRA token from various sources."""
        if self._token:
            return self._token
        try:
            self._token = self._get_file_content(self._token_path).strip()
            return self._token
        except FileNotFoundError:
            print(f'Configuration file {self._token_path} not found, one more attempt will be tried by reading JIRA_TOKEN environment variable, but storing it in a file with properly restrictive permissions might be safer.')

        try:
            self._token = os.environ['JIRA_TOKEN']
            return self._token
        except KeyError:
            print("JIRA_TOKEN environment variable missing")

        self._error(f'All attempts to get a JIRA token failed. Create one in the Jira web interface (see your Profile section) and save only the token string into a file located at {self._token_path} with properly restricted access (preferred), or set it into the JIRA_TOKEN environment variable.')
        return None


    def _write_api_calls(self, data):
        """
        Writes API calls data to a file and/or prints it to stderr.

        If the '_program_args.store_api_calls' attribute is set, the 'data' is appended
        to the file specified by '_program_args.store_api_calls' with a newline character.
        If the '_program_args.show_api_calls' attribute is set, the 'data' is printed to
        stderr.

        Args:
            data (str): The API calls data to be written or printed.
        """
        if self._program_args.store_api_calls:
            with open(self._program_args.store_api_calls, 'a') as f:
                f.write(data)
                f.write('\n')
        if self._program_args.show_api_calls:
                print(data, file=sys.stderr)


    def _get_auth_data(self) -> dict:
        """
        Retrieves authentication data including headers with the JIRA token.
        """
        token = self._get_token()
        auth = {
                "Accept": "application/json",
                "Authorization": "Bearer {token}"
               }
        if not self._log_headers_done:
            self._write_api_calls('#!/usr/bin/env python3')
            self._write_api_calls('# Python 3 snippets that may help you write your script, do not use without proper review')
            self._write_api_calls('import requests, pprint')
            self._write_api_calls(self._log_arg('headers', auth))
            self._log_headers_done = True
        # replace the token string after the header is logged to not leak token
        auth["Authorization"] = auth["Authorization"].format(token=token)
        return auth


    def _get_headers(self) -> dict:
        return self._get_auth_data()


    def _log_arg(self, arg_name, arg):
        """
        Formats an argument name and value for logging purposes.

        Args:
            arg_name (str): The name of the argument.
            arg: The value of the argument.

        Returns:
            str: Formatted argument representation for logging.
        """
        if not arg:
            return f'{arg_name} = None'

        enclosed_arg = f'"{arg}"' if isinstance(arg, str) else f'{arg}'
        return f'{arg_name} = {enclosed_arg}'


    def _api_request(self, method, url, params=None, json=None, fake_return=None):
        headers = self._get_headers()
        log = ['']
        if method == 'post':
            log.append(self._log_arg('json', json))
            log.append(f'response = requests.post("{url}", json=json, headers=headers)')
            if not self._program_args.simulate:
                result = requests.post(url, json=json, headers=headers)
            log.append(f'print(response.ok)')
        elif method == 'put':
            log.append(self._log_arg('json', json))
            log.append(f'response = requests.put("{url}", json=json, headers=headers)')
            if not self._program_args.simulate:
                result = requests.put(url, json=json, headers=headers)
            log.append(f'print(response.ok)')
        elif method == 'get':
            log.append(self._log_arg('params', params))
            log.append(f'response = requests.get("{url}", params=params, headers=headers)')
            if not self._program_args.simulate:
                result = requests.get(url, params=params, headers=headers)
            # not logging how to parse output, leaving this up to calling functions
        else:
            self._error(f'Error: Unsupported method for requests: {method}')
        if self._program_args.simulate or self._program_args.show_api_calls or self._program_args.store_api_calls:
            self._write_api_calls('\n'.join(log))
        if self._program_args.simulate:
            if fake_return:
                return FakeResponse(fake_return)
            self._error(f'Simulating only, ending now.')
        return result


    def _report_api_failure(self, r):
        print(f'FAILURE: Api call failed.')
        print(f'Reason: {r.reason}')
        print(f'Text: {r.text}')
        if self._debug:
            pprint.pprint(r.raw)


    def _print_issue(self, output_format, issue, log_api_if_required=True):
        if log_api_if_required:
            self._write_api_calls("print('{key}'.format(**issue))")
        print(output_format.format(**issue))


    def _print_issues(self, output_format, issues):
        self._write_api_calls("for issue in issues:")
        self._write_api_calls("    print('{key}'.format(**issue))")
        for issue in issues:
            self._print_issue(output_format, issue, log_api_if_required=False)


    def _print_raw_issues(self, issues):
        self._write_api_calls("json.dumps(issues, sort_keys=True, indent=4))")
        print(json.dumps(issues, sort_keys=True, indent=4))


    def _get_file_content(self, filename):
        with open(filename) as f:
            return '\n'.join(f.readlines())


    def _get_issue(self, issue):
        r = self._api_request('get', f"{self.JIRA_REST_URL}/issue/{issue}")
        return r.json()


    def _get_issue_types(self, project):
        """
        Retrieves the issue types for a project from Jira.

        Makes a GET request to the Jira API to fetch the issue types
        for the specified project. Returns a dictionary mapping the
        issue type names to their corresponding IDs.

        Args:
            project (str): The key or ID of the project.

        Returns:
            dict: A dictionary mapping issue type names to their IDs.
        """
        r = self._api_request('get', f"{self.JIRA_REST_URL}/issue/createmeta/{project}/issuetypes")
        data = r.json()
        result = {}
        try:
            result = {t['name']:t['id'] for t in data['values']}
        except (KeyError, IndexError):
            reason = 'unknown' if 'errorMessages' not in data else data['errorMessages'][0]
            self._error(f'Issue types not found. It is possible that project {project} does not exist. Reason given by Jira: {reason}')
        return result


    def _get_fields_mapping(self, project, issue_type, only_required=False):
        """
        Retrieves the field mapping for a specific issue type in a project.

        Makes a GET request to the Jira API to fetch the field mapping
        for the given issue type in the specified project. Returns a
        dictionary mapping field IDs to their corresponding names.

        Args:
            project (str): The key or ID of the project.
            issue_type (str): The name of the issue type.
            only_required (bool): Flag to include only required fields in the mapping.

        Returns:
            dict: A dictionary mapping field IDs to their names.
        """
        issue_types = self._get_issue_types(project)
        mapping = {}
        r = self._api_request('get', f"{self.JIRA_REST_URL}/issue/createmeta/{project}/issuetypes/{issue_types[issue_type]}")
        data = r.json()
        try:
            mapping = { field['fieldId']:field['name'] for field in data['values'] if field['required'] or not only_required }
        except (KeyError, IndexError):
            reason = 'unknown' if 'errorMessages' not in data else data['errorMessages'][0]
            self._error(f'Data not found. It is possible that project {project} has no issue type {issue_type}. Reason given by Jira: {reason}')
        return mapping


    def _get_fields_mapping_for_issue(self, jira_id, only_required=False):
        """
        Retrieves the field mapping for a specific issue type in a project.

        Works similarly to _get_fields_mapping, except the project and issue
        type is specified by a concrete issue.

        See _get_fields_mapping for more information.
        """
        mapping = {}
        r = self._api_request('get', f"{self.JIRA_REST_URL}/issue/{jira_id}/editmeta?expand=projects.issuetypes.fields")
        data = r.json()
        try:
            mapping = { key:data['fields'][key]['name'] for key in data['fields'] if data['fields'][key]['required'] or not only_required }
        except (KeyError, IndexError):
            reason = 'unknown' if 'errorMessages' not in data else data['errorMessages'][0]
            self._error(f'Data not found. It is possible that project {project} has no issue type {issue_type}. Reason given by Jira: {reason}')
        return mapping


    def _get_jql_from_url(self, url) -> str:
        """
        Extracts the JQL (Jira Query Language) from a given URL.
        """
        url_parsed = urllib.parse.urlparse(url)
        jql = ''
        if url_parsed.query != '':
            for url_query in urllib.parse.parse_qsl(url_parsed.query):
                if url_query[0] == 'filter' and len(url_query) == 2:
                    jql = 'filter={}'.format(url_query[1])
                elif url_query[0] == 'jql' and len(url_query) == 2:
                    # not sure how we can only encode the value
                    jql = url_query[1]
        return jql


    def cmd_fields_mapping(self, args):
        """
        Command handler for retrieving and printing field mappings.
        """
        if args.id:
            mapping = self._get_fields_mapping_for_issue(args.id, args.only_required)
        else:
            mapping = self._get_fields_mapping(args.project, args.issue_type, args.only_required)
        print(json.dumps(mapping, sort_keys=True, indent=4))


    def _get_issues(self, ids=None, from_url=None, jql=None, max_results=None, start_at=None):
        """
        Retrieves issues based on issue IDs, a URL with a query, or
        a JQL query. Returns a list of issues.

        Args:
            ids (list): List of issue IDs.
            from_url (str): URL containing a query.
            jql (str): JQL query string.
            max_results (int): Maximum number of results to retrieve.
            start_at (int): Index of the first result to retrieve.

        Returns:
            list: A list of issues.
        """
        output=[]

        # get issues based on ID
        if ids:
            for issue in ids:
                output.append(self._get_issue(issue))

        # get issues based on url with a query
        if from_url:
            jql = self._get_jql_from_url(from_url)

        # get issues based on jql only
        if jql:
            query = urllib.parse.urlencode([('jql',jql), ('maxResults', max_results), ('startAt', start_at)])
            r = self._api_request('get', f"{self.JIRA_REST_URL}/search", params=query)
            self._write_api_calls("issues = response['issues']")
            if r.ok:
                output += r.json()['issues']

        return output


    def cmd_query(self, args):
        """
        Command handler for querying and printing issues.
        """
        output = self._get_issues(args.id, args.from_url, args.jql, args.max_results, args.start_at)

        if args.output_format:
            # use codecs to interpret escape characters
            output_format = codecs.escape_decode(bytes(args.output_format, "utf-8"))[0].decode("utf-8")
        else:
            output_format = self._default_output

        if args.raw:
            self._print_raw_issues(output)
        else:
            self._print_issues(output_format, output)


    def _create_issue(self, input_data, args):
        r = self._api_request('post', f"{self.JIRA_REST_URL}/issue", json=input_data)
        self._write_api_calls("issue = response.json()")
        if not r.ok:
            print(r.text)
            self._error('Issue NOT created.')
        new_issue = r.json()
        # TODO: we can re-load the whole issue again to allow show other fields than key and id
        if args.output_format:
            # use codecs to interpret escape characters
            output_format = codecs.escape_decode(bytes(args.output_format, "utf-8"))[0].decode("utf-8")
        else:
            output_format = self._default_output

        if args.raw:
            self._print_raw_issues(new_issue)
        else:
            self._print_issue(output_format, new_issue)


    def cmd_create(self, args):
        """
        We need to get some JSON structure like this:
        {
           "fields": {
              "project":
              {
                 "key": "TEST"
              },
              "summary": "REST ye merry gentlemen.",
              "description": "Creating of an issue using project keys and issue type names using the REST API",
              "issuetype": {
                 "name": "Bug"
              }
           }
        }
        """
        mapping = self._get_fields_mapping(args.project, args.issue_type, True)
        if args.json:
            input_data = json.loads(args.json)
        elif args.json_file:
            with open(args.json_file, 'r') as f:
                input_data = json.load(f)
        else:
            input_fields = {'project': {'key': args.project}, 'issuetype': {'name': args.issue_type}}
            if not args.summary:
                self._error("Summary field is compulsory")
            input_fields['summary'] = args.summary
            if (args.description and args.description_file):
                self._error("Specify either --description or --description_file, but not both")
            input_fields['description'] = args.description or self._get_file_content(args.description_file)
            input_data = {'fields': input_fields}
        self._debug_print(json.dumps(input_data, sort_keys=True, indent=4))
        self._create_issue(input_data, args)


    def _process_query_links(self, input_data, args):
        if args.link_type and args.link_issue:
            # ensure we only add to existing fields that are created if not exist initially
            if "update" not in input_data:
                input_data["update"] = {}
            if "issuelinks" not in input_data["update"]:
                input_data["update"]["issuelinks"] = []

            input_data["update"]["issuelinks"].append(self._get_link_data(args.link_type, args.link_issue))
            return input_data


    def _update_issue(self, issue, input_data, args):
        input_data = self._process_query_links(input_data, args)
        self._debug_print(f'Issue {issue} being updated with: {input_data}')
        r = self._api_request('put', f"{self.JIRA_REST_URL}/issue/{issue}", json=input_data)
        if r.ok:
            print(f'Issue {issue} updated.')
        else:
            self._report_api_failure(r)
            self._error(f'Issue {issue} NOT updated.')


    def cmd_update(self, args):
        """
        How Bugzilla CLI approached special fields:
        Fields that take multiple values have a special input format.
        Append:    --cc=foo@example.com
        Overwrite: --cc==foo@example.com
        Remove:    --cc=-foo@example.com
        Options that accept this format: --cc, --blocked, --dependson,
            --groups, --tags, whiteboard fields.

        What we expect in Jira:
            <...> --json ' { "fields": { "summary": "rebuild of nodejs-12-container 8.4" } }'
            <...> --json ' {"update": { "labels": [ {"add": "mynewlabel"} ] } }'
            <...> --json ' {"update": { "labels": [ {"remove": "mynewlabel"} ] } }'

        input_data={"update":{"labels":[{"add":"jira-bugzilla-resync"}]}}
        r=requests.put(f"{self.JIRA_REST_URL}/issue/RHELPLAN-95816", json=input_data, headers=headers, verify=False)
        """
        if args.json:
            input_data = json.loads(args.json)
        elif args.json_file:
            with open(args.json_file, 'r') as f:
                input_data = json.load(f)
        else:
            input_data = {}
        if args.id:
            for issue in args.id:
                self._update_issue(issue, input_data, args)


    def _replace_re(self, original_value, key, args):
        if args.set:
            set_data = json.loads(args.set, strict=False)
            output = set_data[key] if key in set_data else original_value
        else:
            output = original_value
        if args.re:
            replace_data = json.loads(args.re)
            if key in replace_data:
                replace_data_key = replace_data[key] if type(replace_data[key]) == list else [replace_data[key]]
                for repl in replace_data_key:
                    output = re.sub(repl['pattern'], repl['replacement'], output)
        return output


    def _get_link_data(self, link_type, issue):
        """
        Returns a valid dictionary structure for a given link type and issue ID
        """
        if link_type in self.link_data:
            type_data = self.link_data[link_type]
        else:
            self._error(f"link_type {link_type} not recognized. Pick one of: " + ','.join(self.link_data.keys()))

        link_data_output = {
            "add": {
              "type": type_data,
                "outwardIssue": {
                  "key": issue
                }
              }
            }

        return link_data_output


    def cmd_clone(self, args):
        """
        Clone an issue with some logic for keeping, changing and removing some specific fields.
        """
        issue = args.id
        original = self._get_issue(issue)
        original_fields = original['fields']

        # start with what is set explicitly by --set
        input_fields = json.loads(args.set, strict=False) if args.set else {}

        # get fields that must be replaced (whether they are replaced or not depends also on --re content)
        fields_for_replace = ['summary', 'description']
        for field in ['project', 'issuetype']:
            if field not in input_fields:
                fields_for_replace.append(field)

        # copy or replace fields
        for field in fields_for_replace + (args.copy_fields if args.copy_fields else []):
            input_fields[field] = self._replace_re(original_fields[field], field, args)

        clon_data = {'fields': input_fields}

        # add a link to the original
        if not args.no_link_back:
            clon_data["update"] = {
              "issuelinks": [ self._get_link_data('clones', args.id) ]
            }

        self._create_issue(clon_data, args)


    def _get_fake_transitions(self):
        """
        Returns hard-coded transitions data for simulating purposes.
        """
        with open(fake_data_dir + '/transitions.json', 'r') as f:
            return json.load(f)

    def _get_transitions(self, issue):
        fake_return = self._get_fake_transitions() if self._program_args.simulate else None
        r = self._api_request('get', f"{self.JIRA_REST_URL}/issue/{issue}/transitions?expand=transitions.fields", fake_return = fake_return)
        if r.ok:
            return r.json()['transitions']
        else:
            self._report_api_failure(r)
            self._error(f'Could not read transitions for issue {issue}.')


    def _filter_transition_id(self, issue, status, resolution):
        """
        Filters and retrieves the transition ID and resolution for a given issue and status.

        Retrieves the transitions for the specified issue and checks if there is a transition
        with the given status. If found, returns a dictionary containing the transition ID and,
        if applicable, the resolution name. If no matching transition is found, raises an error.

        Args:
            issue (str): The ID of the issue.
            status (str): The desired status for the transition.
            resolution (str): The desired resolution for the transition (if applicable).

        Returns:
            dict: A dictionary containing the transition ID and, if applicable, the resolution name.

        Raises:
            Exception: If no matching transition is found for the given issue and status.
        """
        result = {}
        transitions = self._get_transitions(issue)
        for t in transitions:
            if t['name'] == status:
                result['transition'] = {'id': t['id']}
                # just for status, check the given resolution is valid
                if status == 'Closed' and 'resolution' in t['fields']:
                    for r in t['fields']['resolution']['allowedValues']:
                        if r['name'] == resolution:
                            result['fields'] = {'resolution': {'name': resolution}}
                return result
        self._error(f"Cannot find a transition called '{status}' for issue '{issue}'")


    def cmd_move(self, args):
        """
        Move an issue to a different status with some comment and resolution if exists for the target status.
        This requires transition id probably: https://issues.redhat.com/rest/api/2/issue/RHELPLAN-141790/transitions?expand=transitions.fields
        https://community.atlassian.com/t5/Jira-questions/Close-Jira-Issue-via-REST-API/qaq-p/1845399
        """
        if (args.comment and args.comment_file):
            self._error("Specify either --comment or --comment_file, but not both")
        for issue in args.id:
            status = args.status
            input_data = self._filter_transition_id(issue, status, args.resolution)
            r = self._api_request('post', f"{self.JIRA_REST_URL}/issue/{issue}/transitions", json=input_data)
            if r.ok:
                print(f'Issue {issue} moved to {status}.')
            else:
                self._report_api_failure(r)
                self._error(f'Issue {issue} NOT transitioned.')
            if args.comment or args.comment_file:
                comment_data = {'body': args.comment or self._get_file_content(args.comment_file)}
                r = self._api_request('post', f"{self.JIRA_REST_URL}/issue/{issue}/comment", json=comment_data)
                if r.ok:
                    print(f'Comment added to the issue {issue}.')
                else:
                    self._report_api_failure(r)
                    self._error(f'Comment not added to the tissue {issue}.')


    def cmd_access(self, args):
        """
        Checks access to the server by reading a known to exist issue and
        verifying the returned value includes what it should.
        """
        if args.configure:
            token_dir = os.path.dirname(self._token_path)
            if not os.path.exists(token_dir):
                os.mkdir(token_dir, mode = 0o700)
            else:
                s = os.stat(token_dir)
                if s.st_mode & 0o777 != 0o700:
                    self._error(f'Diretory {token_dir} must have 0700 permissions, so nobody else than the owner can read it')
            print(f'Provide a token created through Jira WebUI that will be stored to {self._token_path}:', flush=True)
            self._token = getpass.getpass()
            with open(self._token_path, "w") as f:
                f.write(self._token)

        issues = self._get_issues(ids=['RHELPLAN-141790'])
        if issues[0]['id'] != '14977200':
            self._error('Failure: Access does not look good, at least reading RHELPLAN-141790 did not succeed.')
        print(f'Access to the server {self.JIRA_PROJECTS_URL} looks good.')


    def main(self, fake_args=None) -> int:
        """Main program entry that parses args"""
        description=textwrap.dedent('''\
            Work with JIRA from cmd-line like you liked doing it with python-bugzilla-cli.
            ------------------------------------------------------------------------------
              When working with the tool, check what fields exist in a project you work with.
              Jira is masively configurable, so many fields are available under customfield_12345 name.
              This tool is supposed to hide some of the specifics and is supposed to be an opiniated
              tool for RHEL project specifically.

              Another motivation for this tool is to help people working with Jira API to learn
              the concepts easily, by showing how several basic operations done via CLI would
              look like in a Python script (see the --simulate argument).

              Query JIRA issues:
                You can query issues by ID, JQL or URL (from which we usually extract JQL anyway).
                For stored filters, you can easily use filter=<i> as JQL or part of JQL.
                Results are paginated.

                Examples:
                  {program_name} query --jql 'project = RHELPLAN' --max_results 100 --start_at 200
                  {program_name} query --from-url 'https://issues.redhat.com/issues/?jql=project%20%3D%20%22RHEL%20Planning%22%20and%20issueLinkType%20%3D%20clones%20'
                  {program_name} query --jql 'parent = RHELPLAN-138763' --outputformat '{key}'
                  {program_name} --simulate query --jql 'filter=12363088'

              Updating JIRA issues:
                Consider reading "Updating an Issue via the JIRA REST APIs" section of the Jira API:
                https://developer.atlassian.com/server/jira/platform/updating-an-issue-via-the-jira-rest-apis-6848604/

                Examples:
                  {program_name} update -j RHELPLAN-95816 --json '{"fields": { "summary": "rebuild of nodejs-12-container 8.4.z" } }'
                  {program_name} update -j RHELPLAN-95816 --json '{"update": { "labels": [ {"add": "mynewlabel"} ] } }'
                  {program_name} update -j RHELPLAN-95816 --json '{"update": { "labels": [ {"remove": "mynewlabel"} ] } }'
                  {program_name} update -j RHELPLAN-142727 --json '{"update": {"issuelinks": [{"add": {"outwardIssue": {"key": "RHELPLAN-141789"}, "type": {"inward": "is cloned by", "name": "Cloners", "outward": "clones"}}}]}}'


                Notes:
                  Changing the issue type to sub-task seems to be not possible: https://jira.atlassian.com/browse/JRASERVER-33927

              Creating JIRA issues:
                Pick a project (RHEL is the default), specify summary and description and create an issue.

                Examples:
                  {program_name} new --summary 'Test issue for playing around with Jira API' --description 'testing description with a nice text simulating a text for a <bug> or a <feature>.'  --project RHELPLAN

              Moving to a different status and closing JIRA issues:
                Closing a JIRA issue is just a move to a different status.

                Examples:
                  {program_name} move -j RHELPLAN-141789 --status Closed --resolution 'Not a Bug' --comment 'closing'

              Cloning a Jira issue:
                This is similar to creating, the specified issue is fetched first, then we pick several fields to keep.

                Examples:
                  # Clone an issue with no changes
                  {program_name} clone -j RHELPLAN-141789

                  # Clone an issue and set different issue type and change description using regexp
                  {program_name} clone -j RHELPLAN-141789 --set '{"issuetype": {"name": "Feature"}}' --re '{"description": {"pattern": "issue", "replacement": "bug"}}'

                  # clone RHEL 8 PRP template
                  {program_name} clone  -j RHELPLAN-27509  --re '{"summary": {"pattern": "<package_name>", "replacement": "newfakecomponent"}, "description": [{"pattern": "<package_name>", "replacement": "newfakecomponent"}, {"pattern": "<the package to add>", "replacement": "newfakecomponent"}, {"pattern": "<a bugzilla bug ID>", "replacement": "12345678fake"}]}'
                  {program_name} clone  -j RHELPLAN-27509  --re '{"summary": {"pattern": "<package_name>", "replacement": "newfakecomponent"}}' --set '{"description": "{noformat}\\nDISTRIBUTION BUG: 12345fake\\nPACKAGE NAME: newfakecomponent\\nPACKAGE TYPE: standalone\\nPRODUCT: Red Hat Enterprise Linux 8\\nPRODUCT VERSION: 8.8.0\\nBUGZILLA REQUESTER: fakedevel@redhat.com\\nACG LEVEL: 4\\nQE CONTACT KERBEROS ID: fakeqe\\nQE CONTACT RED HAT JIRA USERNAME: fakeqe@redhat.com\\nQE CONTACT BUGZILLA: rhel-fake-subsystem-qe@redhat.com\\nQE CONTACT IS A USER: NO\\nUSER KERBEROS ID: fakedevel\\nRED HAT JIRA USERNAME: fakedevel@redhat.com\\nBUGZILLA ACCOUNT: fakedevel@redhat.com\\n{noformat}"}'

                  # Clone an issue and add a suffix to the summary
                  {program_name} clone  -j RHELPLAN-141789  --re '{"summary": {"pattern": "$", "replacement": " cloned"}}'
            ''')
        # do not expand anything else than the program name, complicated format
        # would make issues when using f-strings or .format()
        description=description.replace('{program_name}', self.program_name)
        parser = argparse.ArgumentParser(prog=self.program_name, description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
        subparsers = parser.add_subparsers(help='commands')
        parser.add_argument('--show-api-calls', action='store_true', help='Show what API calls the tool performed and with what input. The output is printed to stderr.')
        parser.add_argument('--store-api-calls', help='Store what API calls the tool performed and with what input into a given file. The data are appeneded.')
        parser.add_argument('--simulate', action='store_true', help='Do not proceed with any API calls.')
        parser.add_argument('--debug', action='store_true', help='Show very verbose log of what the tool does.')

        # query command
        parser_query = subparsers.add_parser('query', help='query JIRA issues')
        parser_query.add_argument('-j', '--id', '--jira_id', metavar='ID', type=str, nargs='+',
                                  help='Jira issues ID')
        parser_query.add_argument('--from-url', dest='from_url',
                            help='Use full URL as an argument')
        parser_query.add_argument('--jql', dest='jql',
                            help='Use JQL query')
        parser_query.add_argument('--raw', action='store_true',
                            help='Display raw issue data (JSON)')
        parser_query.add_argument('--start_at', dest='start_at', default=0, help='Pagination, start at which item in the output of a single query')
        parser_query.add_argument('--max_results', dest='max_results', default=self.DEFAULT_MAX_RESULTS, help='Pagination, how many items in the output of a single query, not counting individually requested IDs')

        # the idea here is to use something like print("format from user".format(**issue)) but needs to be validated by some real pythonist for security
        parser_query.add_argument('--outputformat', dest='output_format',
                            help='Print output in the form given. Use str.format string with {key} or {field["duedate"]} syntax. Use --raw to see what keys exist.')
        parser_query.set_defaults(func=self.cmd_query)

        # new command
        parser_new = subparsers.add_parser('new', help='create a new JIRA issue')
        parser_new.set_defaults(func=self.cmd_create)
        parser_new.add_argument('--json',
                                help='Input raw issue data (JSON)')
        parser_new.add_argument('--json_file',
                                help='Input raw issue data from a JSON file')
        parser_new.add_argument('--project', default='RHEL', help='Which project to show fields for (default RHEL)')
        parser_new.add_argument('--issue_type', default='Bug', help='Which issue type do we want to see fields for (default Bug)')
        parser_new.add_argument('--summary', help='A short summary of the issue (must be set if we specify fields separately)')
        parser_new.add_argument('--description', help='Longer description of the issue (either this or description_file must be set if we specify fields separately)')
        parser_new.add_argument('--description_file', help='Longer description of the issue located in a file (either this or description must be set if we specify fields separately)')
        parser_new.add_argument('--link-epic', help='Add an epic to the new issue')
        parser_new.add_argument('--raw', action='store_true',
                            help='Display raw issue data (JSON)')
        parser_new.add_argument('--outputformat', dest='output_format',
                            help='Print output in the form given. Use str.format string with {key} or {field["duedate"]} syntax. Use --json to see what keys exist.')

        # update command
        parser_update = subparsers.add_parser('update', help='update a JIRA issue')
        parser_update.set_defaults(func=self.cmd_update)
        parser_update.add_argument('-j', '--id', '--jira_id', metavar='ID', type=str, nargs='+',
                                   help='Jira issues ID')
        parser_update.add_argument('--json',
                                   help='JSON that defines what should be changed. See "Updating an Issue via the JIRA REST APIs" section of the Jira API: https://developer.atlassian.com/server/jira/platform/updating-an-issue-via-the-jira-rest-apis-6848604/')
        parser_update.add_argument('--json_file',
                                help='Input raw issue data from a JSON file')
        parser_update.add_argument('--comment', help='Longer comment to be added to the issue')
        parser_update.add_argument('--comment_file', help='Longer comment to be added to issue located in a file')
        parser_update.add_argument('--link-type', choices=self.link_data.keys(), help='What type of link to use')
        parser_update.add_argument('--link-issue', metavar='ID', help='Jira issue ID to link to')

        # clone command
        parser_clone = subparsers.add_parser('clone', help='clone a JIRA issue')
        parser_clone.set_defaults(func=self.cmd_clone)
        parser_clone.add_argument('-j', '--id', '--jira_id', metavar='ID', type=str, required = True,
                                   help='Jira issues ID')
        parser_clone.add_argument('--keep', metavar='key', type=str,
                                   help='name of the key to keep in the clone (by default, keys kept are summary, description, labels)')
        parser_clone.add_argument('--remove', metavar='key', type=str,
                                   help='name of the key to remove from the clon (by default, keys kept are summary, description, labels)')
        parser_clone.add_argument('--set', metavar='json', type=str,
                                   help='JSON that defines what should be changed by replacing the content entirely. Example: {"summary": "My new summary"}')
        parser_clone.add_argument('--re', metavar='json', type=str,
                                   help='JSON that defines what should be changed using regexp. The value must be a dict with keys pattern and replacement. Example: {"summary": {"pattern": "<component>", "replacement": "newcomponent"}}')
        parser_clone.add_argument('--no_link_back', action='store_true', help='Do not link back to the original issue (if not specified, the new issue is linked back to the original one using cloned relation)')
        parser_clone.add_argument('--raw', action='store_true',
                            help='Display raw issue data (JSON)')
        parser_clone.add_argument('--outputformat', dest='output_format',
                            help='Print output in the form given. Use str.format string with {key} or {field["duedate"]} syntax. Use --json to see what keys exist.')
        parser_clone.add_argument('--copy_fields', metavar='field', type=str, nargs='+',
                                  help='Fields to be copied from the original issue, can be specified multiple times. If combined with --re, regular expression replacement will be applied for those fields.')

        # move command
        parser_move = subparsers.add_parser('move', help='change a JIRA issue status')
        parser_move.set_defaults(func=self.cmd_move)
        # so far limiting to a single issue
        parser_move.add_argument('-j', '--id', '--jira_id', metavar='ID', type=str, nargs='+', required = True,
                                   help='Jira issues ID')
        parser_move.add_argument('--comment', help='Longer comment to be added to the issue')
        parser_move.add_argument('--comment_file', help='Longer comment to be added to issue located in a file')
        parser_move.add_argument('--status', default='Closed', help='Target status (default: Closed)')
        parser_move.add_argument('--resolution', default='Done', help='Resolution of the closure (default: Done)')

        # fields-mapping command
        parser_fields_mapping = subparsers.add_parser('fields-mapping', help='show fields mapping for a project and issue type (shows only fields available when creating a new issue) or specific issue (shows all fields)')
        parser_fields_mapping.set_defaults(func=self.cmd_fields_mapping)
        parser_fields_mapping.add_argument('--project', default='RHEL', help='Which project to show fields for (default RHEL)')
        parser_fields_mapping.add_argument('-j', '--id', '--jira_id', metavar='ID', type=str, help='Jira issue ID')
        parser_fields_mapping.add_argument('--issue_type', default='Bug', help='Which issue type do we want to see fields for (default Bug)')
        parser_fields_mapping.add_argument('--only_required', action='store_true', help='Print only required fields')

        # access command
        parser_access = subparsers.add_parser('access', help='verifies that the tool is able to access the server')
        parser_access.set_defaults(func=self.cmd_access)
        parser_access.add_argument('--configure', action='store_true', help='Configure access to the Jira server')

        if len(sys.argv) <= 1:
            sys.argv.append('--help')

        args = parser.parse_args(args=fake_args) if fake_args else parser.parse_args()
        self._program_args = args
        self._debug = args.debug

        args.func(args)

        return 0


if __name__ == '__main__':
    ej = EasyJira()
    sys.exit(ej.main())
