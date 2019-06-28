[![CircleCI](https://circleci.com/gh/faisalraja/testhttp.svg?style=svg)](https://circleci.com/gh/faisalraja/testhttp)

# testhttp


testhttp allows you to send HTTP request for testing your endpoints. This is still very incomplete but satisfy my needs at the moment. Feel free to suggest or create changes for updates.

## Features
* The goal is to be compatible with [vscode-restclient](https://github.com/Huachao/vscode-restclient) but with ability to assert results and automate dependencies.
* Run named or by index http definition
* Import other files to re-use http definition
* Set global variables as a context for the scripts

## Install
```bash
pip install testhttp
# -h for help
testhttp -h

# Run a file
testhttp --file sample.http

# Run all files based on glob pattern
testhttp --pattern '/Users/path/to/**/test/*.http'
# Declaring a global variable that will be available for all scripts
testhttp --var host=https://baseurl/
# Automatically remove steps with the same name
testhttp --distinct
```

## Usage
In editor, type an HTTP request as simple as below:
```http
https://example.com/comments/1

###

# @name postToExample
POST https://example.com/comments HTTP/1.1
content-type: application/json

{
    "name": "sample",
    "time": "Wed, 21 Oct 2015 18:27:50 GMT"
}

>>>

assert {{response.status_code}} == 404
```
Save it as sample.http then run the command below:
```bash
# add --verbose to see request and response information 
# add --debug for debug info
testhttp --file.sample.http --name postToExample
```

## Import
You can import other files by:
```http
@import other_file.http

###

... rest of your http info
```
This will do a lookup relative to current file. Without specifying --name or --index it will still only run all tests under the current file and will only run things it depends on.

## Variables & Dependencies
Running by name will result in execution of it's variable dependencies. This way you can only test specific spec and it will still work with single command.
```http
@user = hello
@password = world
@baseUrl = https://example.com

# @name login
POST {{baseUrl}}/api/login HTTP/1.1
content-type: application/json

{
    "username": "{{user}}",
    "password": "{{password}}"
}

>>>

assert {{response.status_code}} == 200

###

@token = {{login.response.body.token}}

# @name getCurrentUser
GET {{baseUrl}}/api/me HTTP/1.1
content-type: application/json
Authorization: {{token}}

>>>

assert {{response.status_code}} == 200
assert {{response.body.username}} == {{user}}
```
Running only getCurrentUser will automatically run login since it depends on login in the token variable.

