#!/usr/bin/python
import subprocess
import operator
import time
import sys
import os
import re

def parse_file(file_content):
    def parse_block(lines,bdeep=0):
        deep=0
        result = {}
        current_key = None
        nested_lines = []
        for line in lines:
            #if bdeep == 0:
            #    print(current_key)
            #    print(deep)
            if "{" == line.strip():
                deep += 1  # Increase the depth when encountering an opening brace
                if deep == 1:
                    current_key = nested_lines[-1].strip()[1:-1] # Last line is active key
                    nested_lines = []
                elif deep > 1:
                    nested_lines.append(line)
            elif "}" == line.strip():
                deep -= 1 # Decrease the depth when encountering a closing brace
                if deep == 0:
                    result[current_key] = parse_block(nested_lines,bdeep+1)
                elif deep > 0:
                    nested_lines.append(line)
            else:
                parts = re.split(r'\s+', line.strip(), maxsplit=1)
                if len(parts) == 2:
                    key, value = parts
                    if deep == 0:
                        result[key[1:-1]] = value[1:-1]
                    nested_lines.append(line)
                elif len(parts) == 1 and parts[0]:
                    nested_lines.append(line)

        # Process any remaining nested lines after the loop ends
        #if current_key is not None:
        #    result[current_key] = parse_block(nested_lines)

        return result


    lines = file_content.split('\n')
    parse = parse_block(lines)
    return parse



def save_to_file(data, file_path):
    def format_block(data, indentation=0):
        result = ""
        for key, value in data.items():
            if isinstance(value, dict):
                result += '\t' * indentation + f'"{key}"\n'
                result += '\t' * indentation + '{\n'
                result += format_block(value, indentation + 1)
                result += '\t' * indentation + '}\n'
            else:
                result += '\t' * indentation + f'"{key}"\t\t"{value}"\n'
        return result

    with open(file_path, 'w') as file:
        file.write(format_block(data))

def load_from_file(file_path):
    with open(file_path, 'r') as file:
        content = file.read()
    return parse_file(content)


def get_steam_app_info(app_id):
    match = None
    # Run SteamCMD command and capture output
    command = ['steamcmd', '+app_info_print', str(app_id), '+quit']
    try:
        result = subprocess.check_output(command, timeout=10).decode("utf-8") # ###
    except:
        return match

    # Extract Manifest block
    start = result.find("\n{\n") # find start of manifest
    end = result.rfind("\n}\n") # find end of manifest
    if start != -1 and end != -1:
        match = "\"" + str(app_id) + "\"\n" + result[start+1:end+2] # add id back to the front and save as result manifest

    return match # return manifest or none (if manifest not found)

def calculate_expression(expression):
    operators = {'+': operator.add, '-': operator.sub, '*': operator.mul, '/': operator.truediv}

    # Add spaces around operators except for the multiplication operator
    expression = expression.replace('*', ' * ').replace('/', ' / ').replace('+', ' +').replace('-', ' -')

    tokens = expression.split()

    currend_result = 0
    pending_operand = "+"  # To store an operand that needs an operator
    for token in tokens:
        if token.isdigit() or (token[0] == '-' and token[1:].isdigit()) or (token[0] == '+' and token[1:].isdigit()):
            currend_result = operators[pending_operand](currend_result, int(token))
        elif token in operators:
            pending_operand = token

    return currend_result


def load_branches(cache,cachetime,app_id,refresh="60*60*24"): # Refresh branches each 24 hours, else use cache { ... }
    manifest_data = None
    div = 0
    refresh = calculate_expression(str(refresh))
    try:
        refresh = int(refresh)
    except:
        print("error on calculation \"" + str(refresh) + "\" using default (60*60*24) each 24 hours")
        refresh = 60*60*24

    if cachetime == "":
        div = 0
    else:
        div = int(time.time()) - int(cachetime)
    if div >= int(refresh) or cache == "" or cache.get(str(app_id),None) == None:
        manifest_data = get_steam_app_info(app_id)
        if manifest_data:
            parse = parse_file(manifest_data)
            cachetime = int(time.time())
            cache = parse
        else:
            parse = None
    else:
        parse = cache

    if parse:
        publicbranches  = []
        branches = parse[str(app_id)]['depots']['branches']
        for key in branches:
            if branches[key].get("pwdrequired",0) == 0:
                if key == "public":
                    publicbranches.append("")
                else:
                    publicbranches.append(key)

        return publicbranches, cache, cachetime

    return "", cache, cachetime

def load_manifest_file(manifest,app_id):
    manifile = manifest["base"] + str(app_id) + manifest["ext"]
    if os.path.isfile(manifile):
        return load_from_file(manifile)
    return ""

def save_manifest_file(content,manifest,app_id):
    manifile = manifest["base"] + str(app_id) + manifest["ext"]
    if content.get("AppState", {}).get("installdir",None) == None:
        print("skipping saving manifest since \"installdir\" missing (file probably missing)")
    else:
        save_to_file(content,manifile)

def swich_version(manifest,versions,passbeta,branches,short,argreqest):
    if manifest == "":
        if passbeta == "﻿":  # uses ZERO WIDTH NO-BREAK SPACE
            manifest = versions[""]
        else:
            manifest = versions[passbeta]
    if manifest == "":
        manifest = {}
    gamename = manifest.get("AppState", {}).get("name", "Game")
    activedir = manifest.get("AppState", {}).get("installdir", "Game")
    activebeta = manifest.get("AppState", {}).get("UserConfig", {}).get("BetaKey",None)
    if activebeta == None:
        activebeta = passbeta
    if activebeta == "﻿": # uses ZERO WIDTH NO-BREAK SPACE
        if argreqest == "0" or argreqest == "-":
            argreqest = ""
        activebeta = ""
    newbranch = ""
    if argreqest == "-":
        newbranch = branches[(branches.index(activebeta) + len(branches) - 1) % len(branches)]
    elif argreqest.isnumeric() and argreqest != "0" and (int(argreqest) <= len(branches) or int(argreqest) >= 0-len(branches)):
        argreqest = int(argreqest)
        if argreqest > 0:
            newbranch = branches[argreqest - 1]
        elif argreqest < 0:
            newbranch = branches[argreqest]
    elif argreqest in branches:
        newbranch = argreqest
    #elif argreqest in short.values(): # Optional section for checking the short version name
    #    for fbran, shver in short.items():  # for name, age in dictionary.iteritems():  (for Python 2.x)
    #        if shver == argreqest:
    #            newbranch = fbran
    else: # argreqest == "0" # default circle
        if argreqest != "0":
            print("unmatched version using 0 (circle around)")
        newbranch = branches[(branches.index(activebeta) + 1) % len(branches)]

    oldshort = short.get(activebeta,"﻿") # uses ZERO WIDTH NO-BREAK SPACE
    if oldshort == "﻿": # uses ZERO WIDTH NO-BREAK SPACE
        if len(activebeta.replace(".","")) == 0:
            oldshort = ""
        if len(activebeta.replace(".","")) == 1:
            oldshort = str(activebeta.replace(".","").upper())
        else:
            oldshort = str(activebeta.replace(".","")[:2].upper())

    manifest.setdefault("AppState", {})
    manifest["AppState"].setdefault("MountedConfig", {})
    manifest["AppState"].setdefault("UserConfig", {})

    manifest["AppState"]["MountedConfig"]["BetaKey"] = activebeta
    if manifest["AppState"].get("installdir",None) != None:
        manifest["AppState"]["installdir"] = gamename + oldshort

    newmanifest = versions.get(newbranch,"")

    if newmanifest == "":
        newmanifest = dict(manifest)
    newshort = short.get(newbranch,"﻿") # uses ZERO WIDTH NO-BREAK SPACE
    if newshort == "﻿": # uses ZERO WIDTH NO-BREAK SPACE
        if len(newbranch.replace(".","")) == 0:
            newshort = ""
        if len(newbranch.replace(".","")) == 1:
            newshort = str(newbranch.replace(".","").upper())
        else:
            newshort = str(newbranch.replace(".","")[:2].upper())

    newmanifest["AppState"]["UserConfig"]["BetaKey"] = newbranch
    newmanifest["AppState"]["MountedConfig"]["BetaKey"] = newbranch
    if newmanifest["AppState"].get("installdir",None) != None:
        newmanifest["AppState"]["installdir"] = gamename + newshort


    returnval = {
        "beta":newbranch,
        "new":newmanifest,
        "short":newshort,
        "oldbeta":activebeta,
        "old":manifest,
        "oldshort":oldshort
    }
    return returnval

def report_to(first,then):
    runonchange = []
    if first == "":
        first = "public"
    if then == "":
        then = "public"
    if first == then:
        message = 'no need to swich versions to "' + first + '"'
    else:
        message = 'swiching from "' + first + '" to "' + then + '"'
        if pathsym == "/": #run on linux / mac on version change
            runonchange = ["kill $(pidof steam)","kill $(pidof steam.exe)"] # commands to run on version change (default works for linux and mac)
        else: #run on windows on version change
            runonchange = ["taskkill /IM \"steam.exe\" /F"]
    try:
        subprocess.run(['notify-send', '-a', 'SGS', '-i', 'steam', '-t', '2000', message])
    except:
        pass
    for i in runonchange:
        try:
            os.system(i)
        except:
            pass


def load_conf(file_path):
    defaults = {
        "app_id": 526870, # game id default = Satisfatory
        "beta": "﻿", # the active beta if file missing # uses ZERO WIDTH NO-BREAK SPACE
        "manifest": { # how to construced appmanifest (appmanifest_%gameid%.acf)
            "base": "appmanifest_",
            "ext": ".acf"
        },
        "refresh": "60*60*24",
        "shortver":{"":""}, # "experimental":"EX" # "" = public
        "versions":{"":""}, # "experimental":{ "AppState" { ...%FULLDATA%... }} # "" = public
        "cachetime": "", # unix time of last updated cache
        "cache": "" # currend game steam info cache
    } # here add defaults later
    if os.path.isfile(file_path): # if file exists load file
        defaults = defaults | load_from_file(file_path) # merge config with defaults

    return defaults

def arg_struct(args):
    get = ""
    gamever = "0"
    gid = None
    for i in args:
        if i == "id":
            get = "id"
        elif i == "h" or i == "-h" or i == "--help" or i == "help":
            print("h\t\tTo display this help and exit\nid GAMEID\tTo set the game (id) the script uses\nVERSION\t\tValid values are\n\t\t\t0 to cicle (default), - to reverse cicle\n\t\t\tINDEX to select a index (eg 2 gets branch 2, -2 gets 2end last)\n\t\t\tNAME to select name (eg '' for public or experimental)")
            exit() # Exit on help
        else:
            if get == "id":
                gid = i
            else:
                gamever = i
                get = ""
    return [gid, gamever]


if __name__ == "__main__":
    scriptdir = os.path.dirname(os.path.realpath(__file__))
    scriptn = sys.argv[0].split(os.sep)[-1]
    getend = scriptn.split(".")
    if len(getend) > 1:
        onlyend = getend[-1]
        getend.pop()
        sname = ".".join(getend)
    else:
        onlyend = ""
        sname = getend[0]

    storefile = sname + ".txt"
    conf = load_conf(storefile)

    args = arg_struct(sys.argv[1:])
    if args[0]:
        conf["app_id"] = args[0]

    branches, conf["cache"], conf["cachetime"] = load_branches(conf["cache"], conf["cachetime"], conf["app_id"], conf["refresh"])
    if branches == "":
        branches = conf["versions"].keys()

    manifest = load_manifest_file(conf["manifest"], conf["app_id"])

    retconf = swich_version(manifest,conf["versions"],conf["beta"],branches,conf["shortver"],args[1])

    conf["versions"][retconf["oldbeta"]] = retconf["old"]
    conf["shortver"][retconf["oldbeta"]] = retconf["oldshort"]
    manifest = retconf["new"]
    conf["versions"][retconf["beta"]] = retconf["new"]
    conf["shortver"][retconf["beta"]] = retconf["short"]
    conf["beta"] = retconf["beta"]

    report_to(retconf["oldbeta"],retconf["beta"])

    save_manifest_file(manifest, conf["manifest"], conf["app_id"])
    save_to_file(conf, storefile)