import subprocess
import shutil
import time
import json
import sys
import os

scriptdir = os.path.dirname(os.path.realpath(__file__))
scriptn = sys.argv[0].split(os.sep)[-1]
getend = scriptn.split(".")
if len(getend) > 1:
    onlyend = getend[-1]
    getend[-1] = ""
    sname = ".".join(getend)
storefile = sname + ".json"

if os.path.isfile(scriptdir + os.sep + storefile) == True:
    f = open(scriptdir + os.sep + storefile)
    gameinfo = json.loads(f.read())
    f.close()
else:
    gameinfo = {
        "gamename" : "Satisfatory",
        "gameid" : "526870",
        "versions" : [
            ["",""],
            ["EX","experimental"] #First entry if foldername in combination whit gamename in front of it so "SatisfatoryEX" here
                                #Second entry is steam internal version name
        ]
    }
    f = open(scriptdir + os.sep + storefile, "w")
    f.write(json.dumps(gameinfo, indent=4, separators=(',', ': ')))
    f.close()

#scriptdir = os.path.dirname(os.path.realpath(sys.argv[0]))
pathsym = os.sep

# External commands (to remove the commands emty the lists)
notifycmd = ["notify-send -a \"Version Swicher\" -i steam-native -t 4000 ",""] # this will add the list items together, add the message in between and run the command, default will work on the kde plasma desktop (other systems not tested)
if pathsym == "/": #run on linux / mac on version change
    runonchange = ["kill -9 $(pidof steam)","kill -9 $(pidof steam.exe)"] # commands to run on version change (default works for linux and mac)
else: #run on windows on version change
    runonchange = ["taskkill /IM \"steam.exe\" /F"]

waitbexittime = 2
gamevfile = scriptdir + pathsym + "appmanifest_" + gameinfo["gameid"] + ".acf"

# help section
if len(sys.argv) < 2 or sys.argv[1] == "--help" or sys.argv[1] == "-h" or sys.argv[1] == "h":
    print("Use the following characters as arguments (only one can be used)")
    print("Use 'h' for this help message and exit (whitout argumets this will also start help but will continue as if 's' was supplied)")
    print("Use 's' to switch versions")
    print("\tEg.   script.py s    will switch versions")
    print("Use 'r' to reverse switch versions")
    print("Use any number it will use the corespondig version from the gameinfo dict")
    print("\tEg.   script.py 1    will start version " + gameinfo["versions"][1][1])
    print("The script is now going to use 's' unless 'h' was used")
    if len(sys.argv) > 1:
        print("Exiting")
        time.sleep(waitbexittime)
        exit()
    print("")

#get action
MyArgs = sys.argv
MyArgs.pop(0)
MyArgs = ["s"] + MyArgs
action = ""
for i in MyArgs:
    if i == "s":
        action = "+"
    elif i == "r":
        action = "-"
    else:
        try:
            int(i)
        except:
            pass
        else:
            action = str(int(i))
if action == "":
    print("No argument action found\nExiting")
    time.sleep(waitbexittime)
    exit()

#edit file
if os.path.exists(gamevfile):
    ff = open(gamevfile)
    content = ff.read()
    ff.close()
    listcontent = content.split("\n")
    newcont = ""
    qver = False
    qdir = False
    for i in listcontent:
        then = i.split("\"")
        if len(then) > 3 and then[1] == "installdir":
            qdir = True
        elif len(then) > 3 and then[1] == "BetaKey":
            qver = True
            thekey = then[3]
    keyid = -1
    for i in range(0,len(gameinfo["versions"])):
        if gameinfo["versions"][i][1] == thekey:
            if keyid != -1:
                print("Warning there are multiple copys of the same version in the game list,\nthis will mean this script will always use the last one,\nso it might skip a lot of entrys")
            keyid = i
    if keyid == -1:
        keyid = 0
    same = False
    if action == "+":
        newkey = keyid + 1
    elif action == "-":
        newkey = keyid - 1
    else:
        newkey = int(action)
        if newkey == keyid:
            same = True
    if newkey > len(gameinfo["versions"])-1:
        newkey = 0
    elif newkey < 0:
        newkey = len(gameinfo["versions"])-1
    notifyfu = ""
    try:
        len(notifycmd)
    except:
        notifycmd = ["",""]
    else:
        if len(notifycmd) == 0:
            notifycmd = ["",""]
        elif len(notifycmd) == 1:
            notifycmd += [""]

    for i in notifycmd:
        if notifyfu == "":
            notifyfu += i
        else:
            if same == False:
                gameinfo["versions"][keyid].insert(2, gameinfo["versions"][keyid][1])
                gameinfo["versions"][newkey].insert(2, gameinfo["versions"][newkey][1])
                if gameinfo["versions"][keyid][1] == "":
                    gameinfo["versions"][keyid][2] = "-None-"
                if gameinfo["versions"][newkey][1] == "":
                    gameinfo["versions"][newkey][2] = "-None-"
                notifyfu += "\"Version was on " + gameinfo["versions"][keyid][2] + " Now it is on " + gameinfo["versions"][newkey][2] + "\"" + i
                print("Version was on " + gameinfo["versions"][keyid][2] + " Now it is on " + gameinfo["versions"][newkey][2])
            else:
                gameinfo["versions"][keyid].insert(2, gameinfo["versions"][keyid][1])
                if gameinfo["versions"][keyid][1] == "":
                    gameinfo["versions"][keyid][2] = "-None-"
                notifyfu += "\"Version is allready on " + gameinfo["versions"][keyid][2] + " no need to change it\"" + i
                print("Version is allready on " + gameinfo["versions"][keyid][2] + " no need to change it")
    if notifycmd[0] != "":
        try:
            os.system(notifyfu)
        except:
            pass
    if qdir == False:
        print("The installdir is missing or two short\nToo fix this change the version,\nrestart Steam,\nchange version back and\nrestart steam\nExiting")
        time.sleep(waitbexittime)
        exit()
    if qver == False:
        print("Version entry missing or two short download a non default version to generate then enrty\nIf you are allready on a beta version change the version,\nrestart Steam,\nchange version back and\nrestart steam \nExiting")
        time.sleep(waitbexittime)
        exit()
    for i in listcontent:
        then = i.split("\"")
        if len(then) > 3 and then[1] == "installdir":
            then[3] = gameinfo["gamename"] + gameinfo["versions"][newkey][0]
            then.pop(-1)
            newcont += "\n"
            for j in then:
                newcont += j + "\""
        elif len(then) > 3 and then[1] == "BetaKey":
            then[3] = gameinfo["versions"][newkey][1]
            then.pop(-1)
            newcont += "\n"
            for j in then:
                newcont += j + "\""
        else:
            if newcont == "":
                newcont += i
            else:
                newcont += "\n" + i

    oldfile = scriptdir + pathsym + "appmanifest_" + gameinfo["gameid"] + "_backup" + gameinfo["versions"][keyid][0] + ".acf"
    bacfile = scriptdir + pathsym + "appmanifest_" + gameinfo["gameid"] + "_backup" + gameinfo["versions"][newkey][0] + ".acf"
    if same == False:
        if os.path.exists(bacfile):
            shutil.copy(gamevfile, oldfile)
            shutil.copy(bacfile, gamevfile)
        else:
            shutil.copy(gamevfile, oldfile)
            ff = open(gamevfile, "w")
            ff.write(newcont)
            ff.close()
            shutil.copy(gamevfile, bacfile)
        for i in runonchange:
            try:
                os.system(i)
            except:
                pass
    else:
        shutil.copy(gamevfile, bacfile)


else:
    print("You might have placed this file in the wrong folder\nIt needs to be in your Steam" + pathsym + "steamapps folder\nAlso the game " + gameinfo["gamename"] + " should be installed allready\nExiting")
    time.sleep(waitbexittime)
    exit()


