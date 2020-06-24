import sys
import glob
import os
import argparse
import requests
import re
import random
import collections

version = '0.6.5'
verbose = False
debug = False
stop_on_fail = False
system_vars = {}


def log(message, exit_code=None, end=None):
    print(message, end=end)
    if exit_code is not None:
        exit(exit_code)


class HTTPObject:
    def __init__(self, data, processor, filepath):
        self.method = 'GET'
        self.url = None
        self.version = 'HTTP/1.1'  # ignored
        self.headers = {}
        self.body = None
        self.data = data
        self.meta = {}
        self.vars = {}
        self.eval_vars = {}
        self.tests = []
        self.ran = False
        self.test_result = None
        self.response = None
        self.processor = processor
        self.file = filepath

        self.parse_meta()

    def parse_meta(self):
        lines = self.data.split('\n')
        start_headers = False
        start_body = False
        start_test = False
        body = []
        for line in lines:
            line = line.strip()
            if line.startswith('# @'):
                meta = line[3:].split(' ')
                if len(meta) == 2:
                    self.meta[meta[0]] = meta[1]
            elif line.startswith('@') and '=' in line:
                eq_idx = line.find('=')
                k = line[1:eq_idx].strip()
                v = line[eq_idx+1:].strip()
                if '{{' in line and '}}' in line:
                    self.eval_vars[k] = v
                else:
                    self.vars[k] = v
            elif line.startswith('GET') or line.startswith('POST') or line.startswith('PATCH') or line.startswith('PUT') or line.startswith('DELETE') or line.startswith('http'):
                start_headers = True
                part = line.split(' ')
                if line.startswith('http'):
                    self.url = part[0]
                else:
                    self.method = part[0]
                    self.url = part[1]
            elif start_headers:
                if not line.strip():
                    start_headers = False
                    start_body = True
                elif ':' in line:
                    idx = line.find(':')
                    self.headers[line[:idx].strip()] = line[idx+1:].strip()
            elif start_body:
                if line.startswith('>>>'):
                    start_body = False
                    start_test = True
                elif line.strip():
                    body.append(line)
            elif start_test:
                if line.startswith('assert'):
                    self.tests.append(line[6:].strip())

        if body:
            self.body = '\n'.join(body)

    def parse_headers(self):
        headers = {}
        for key in self.headers:
            headers[self.replace_vars(key)] = str(self.replace_vars(
                self.headers[key]))
        return headers

    def replace_vars(self, text, for_test=False):
        def wrap_quote(txt):
            if for_test and type(txt) is str:
                if "'" in txt or '\n' in txt:
                    return '"""{}"""'.format(txt)
                return "'{}'".format(txt)
            return txt

        if text is None:
            text = ''
        else:
            if '{{' in text and '}}' in text:
                for key in self.vars:
                    if '{{' + key + '}}' == text:
                        return wrap_quote(self.vars[key])
                    else:
                        text = text.replace(
                            '{{' + key + '}}', str(wrap_quote(self.vars[key])))

            eval_vars = re.findall("{{.*?}}", text)
            if eval_vars:
                for eval_var in eval_vars:
                    v = eval_var[2:-2]
                    if v not in self.vars:
                        val = self.processor.evaluate(
                            v, self if for_test else None)

                        # check if direct map
                        if len(eval_vars) == 1 and eval_var == text:
                            text = val
                        else:
                            # evalulate to '' if no value
                            orig = '{{' + v + '}}'                            
                            text = text.replace(orig, 
                                str(wrap_quote(val if orig != val else '')))
                        # do not store built-in functions or context tokens
                        if not (v.startswith('$') or v.startswith('response')):
                            self.vars[v] = val

        return text

    def run(self):
        if not self.ran:
            if self.meta.get('skip') == 'true':
                self.ran = True
                log('Skipped {}'.format(self.meta.get('name', self.url)))
                return
            if self.eval_vars:
                for key in self.eval_vars:
                    self.vars[key] = self.replace_vars(self.eval_vars[key])
                self.eval_vars = {}

            body = self.replace_vars(self.body)
            inline_files = re.findall(r'^(<\s.+)', body, flags=re.MULTILINE)
            if inline_files:
                for inline_file in inline_files:
                    path = inline_file[1:].strip()
                    if path.startswith('.'):
                        path = os.path.join(self.processor.cwd, path)

                    if not os.path.exists(path):
                        log('File "{}" not found'.format(path), 1)
                    data = open(path, 'rb').read()
                    if len(inline_files) == 1 and inline_file == body:
                        body = data
                    else:
                        body = body.replace(inline_file, data.decode())

            url = self.replace_vars(self.url)
            headers = self.parse_headers()
            log("Running '{}' in {}".format(self.meta.get('name', self.url), self.file))
            if verbose:
                log('Request: {} {} {}'.format(
                    self.method, url, len(body) if len(body) > 1000 else body))

            self.response = requests.request(self.method,
                                             headers=headers,
                                             url=url,
                                             data=body)
            if verbose:
                log('Response: {} {}'.format(
                    self.response.status_code, self.response.text))
            self.ran = True

    def run_tests(self):
        if self.test_result is None:
            success_count = 0
            failed_count = 0
            for test in self.tests:
                code = self.replace_vars(test, True)
                try:
                    if eval(code):
                        success_count += 1
                    else:
                        failed_count += 1
                        log("  Failed test: {}".format(code), exit_code=1 if stop_on_fail else None)
                except Exception as e:
                    failed_count += 1
                    log("  Failed test: {} \n    Exception: {}".format(code, e), exit_code=1 if stop_on_fail else None)
            if success_count:
                log("PASSED: {}".format(success_count))
            if failed_count:
                log("FAILED: {}".format(failed_count))
            self.test_result = failed_count == 0
        return self.test_result


class HTTPProcessor:
    def __init__(self, files, vars):
        self.http_opjects = []
        self.http_objects_by_name = {}
        self.vars = {}
        self.success = 0
        self.failures = 0
        self.cwd = None

        for variable in (vars or []):
            var_key_value = variable.split('=')
            self.vars[var_key_value[0]] = var_key_value[1]

        for file in files:
            if not os.path.exists(file):
                log('File "{}" not found'.format(file), 1)

            self.parse_http(file, False)

    def parse_http(self, file, is_import=False):
        if self.cwd is None and not is_import:
            self.cwd = os.path.dirname(file)
        contents = list(map(lambda s: s.strip(), open(
            file, 'r').read().split('###')))
        if len(contents) > 0 and '@import' in contents[0]:
            imports = contents.pop(0).strip().split('\n')
            for line in imports:
                if line.startswith('@import'):
                    path = os.path.join(
                        os.path.dirname(file), line[7:].strip())
                    if not os.path.exists(path):
                        log('Import path "{}" not found'.format(path), 1)

                    self.parse_http(path, True)

        for content in contents:
            http_object = HTTPObject(content, self, file)
            self.vars.update(http_object.vars)

            if 'name' in http_object.meta:
                self.http_objects_by_name[http_object.meta['name']
                                        ] = http_object
            if not is_import:
                self.http_opjects.append(http_object)

    def evaluate(self, token, http_object=None):
        if token in system_vars:
            return system_vars[token]
        elif token.startswith('$randomInt'):
            t = token.split(' ')
            if len(t) != 3:
                raise Exception('Invalid token "{}"'.format(token))
            n = random.randint(int(t[1]), int(t[2]))
            return str(n)

        if '.' not in token:
            # a variable that hasn't been populated
            if token in self.vars:
                return self.vars[token]
            for key in self.http_objects_by_name:
                http_object = self.http_objects_by_name[key]
                if token in http_object.eval_vars:
                    self.run_http_object(http_object)
                    return self.evaluate(token)

        current_http_object = http_object
        current_object = None
        for val in token.split('.'):
            if current_http_object is None and val in self.http_objects_by_name:
                current_http_object = self.http_objects_by_name[val]
                self.run_http_object(current_http_object)
            elif current_http_object is not None:
                if val == 'response':
                    current_object = current_http_object.response
                elif current_object is not None:
                    if val == 'body':
                        try:
                            current_object = current_object.json()
                        except:
                            current_object = current_object.text
                    elif type(current_object) in (dict, requests.structures.CaseInsensitiveDict):
                        current_object = current_object.get(val, None)
                    elif type(current_object) is list:
                        try:
                            current_object = current_object[int(val)]
                        except:
                            current_object = None
                    else:
                        try:
                            current_object = getattr(current_object, val, None)
                        except:
                            current_object = None

        return current_object

    def run_http_object(self, http_object):
        http_object.vars.update(self.vars)
        http_object.run()
        self.vars.update(http_object.vars)
        if debug:
            log('VARS: {}'.format(self.vars))
        return http_object.run_tests()

    def run(self, name=None, index=None, post_name=None, pre_name=None, distinct=False):

        if pre_name:
            for n in pre_name.split(','):
                if n not in self.http_objects_by_name:
                    log('Pre-Name "{}" not found'.format(n), 1)
                self.run_http_object(self.http_objects_by_name[n])

        if name:
            for n in name.split(','):
                if n not in self.http_objects_by_name:
                    log('Name "{}" not found'.format(n), 1)
                self.run_http_object(self.http_objects_by_name[n])
        elif index is not None:
            total_objects = len(self.http_opjects)
            if index < 0 or index >= total_objects:
                log("Index must be greater than 0 and less than {}".format(
                    total_objects), 1)
            else:
                self.run_http_object(self.http_opjects[index])
        else:

            http_objects = []
            if distinct:
                seen = collections.OrderedDict()

                for item in self.http_opjects:
                    seen[item.meta.get('name', item.url)] = item

                http_objects = seen.values()
            else:
                http_objects = self.http_opjects


            for http_object in http_objects:
                self.run_http_object(http_object)

        if post_name:
            for n in post_name.split(','):
                if n not in self.http_objects_by_name:
                    log('Post-Name "{}" not found'.format(n), 1)
                self.run_http_object(self.http_objects_by_name[n])

        for http_object in self.http_opjects:
            if http_object.ran:
                if http_object.test_result is True:
                    self.success += 1
                elif http_object.test_result is False:
                    self.failures += 1
        return self.failures == 0


def cmd():
    global verbose, stop_on_fail, debug
    parser = argparse.ArgumentParser(description='Run http tests')
    parser.add_argument('--file',
                        help='test a specific file or comma delimited file paths',
                        action='append')
    parser.add_argument('--var',
                        help='add a variable needed for the scripts (useful for environmental variables)',
                        action='append')
    parser.add_argument('--pattern',
                        help='test a files matching a pattern "path/to/*.http"')
    parser.add_argument('--name',
                        help='test a specific name within the file or comma delimited names')
    parser.add_argument('--pre-name',
                        help='run a name or comma delimited before starting any tests')
    parser.add_argument('--post-name',
                        help='run a name or comma delimited after all tests are done running (this will not re-run on the same session if already executed)')
    parser.add_argument('--index', type=int,
                        help='test a specific http with a positional index starts with 0')
    parser.add_argument('--distinct',
                        help='remove tests with the same name (usefull when running multiple independent tests)',
                        action='store_true')
    parser.add_argument('--stop_on_fail', dest='stop_on_fail',
                        action='store_true', help='Stop tests on fail')
    parser.add_argument('--verbose', dest='verbose',
                        action='store_true', help='Print more info')
    parser.add_argument('--debug', dest='debug',
                        action='store_true', help='Print debug info')
    parser.add_argument('--version', dest='version',
                        action='store_true', help='Print current version')

    args = parser.parse_args()
    if args.version:
        log('testhttp v{}'.format(version), 0)
    if args.verbose:
        verbose = True
    if args.stop_on_fail:
        stop_on_fail = True
    if args.debug:
        debug = True
    variables = args.var
    files = args.file
    if not files and args.pattern:
        files = glob.glob(args.pattern)

    if files:
        http_processor = HTTPProcessor(files, variables)
        run_success = http_processor.run(
            name=args.name,
            index=args.index,
            post_name=args.post_name,
            pre_name=args.pre_name,
            distinct=args.distinct
        )
        message = 'PASSED: {} FAILED: {}'.format(
            http_processor.success,
            http_processor.failures
        )
        if run_success:
            log("Success [{}]".format(message), 0)
        else:
            log("Failed [{}]".format(message), 1)
