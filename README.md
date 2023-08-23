# SteamGameSwitcher Main
https://codeberg.org/marvin1099/SteamGameSwitcher  
https://codeberg.org/marvin1099/SteamGameSwitcher#description  
https://codeberg.org/marvin1099/SteamGameSwitcher#download  
https://codeberg.org/marvin1099/SteamGameSwitcher#install  
https://codeberg.org/marvin1099/SteamGameSwitcher#customgames  
https://codeberg.org/marvin1099/SteamGameSwitcher#shortcut  
https://codeberg.org/marvin1099/SteamGameSwitcher#usage  
# SteamGameSwitcher Backup
https://github.com/marvin1099/SteamGameSwitcher   
https://github.com/marvin1099/SteamGameSwitcher#description  
https://github.com/marvin1099/SteamGameSwitcher#download  
https://github.com/marvin1099/SteamGameSwitcher#install  
https://github.com/marvin1099/SteamGameSwitcher#customgames  
https://github.com/marvin1099/SteamGameSwitcher#shortcut  
https://github.com/marvin1099/SteamGameSwitcher#usage  
  
# Description
A simple python script to switch steam gameversions.  
Mainly (and in default) made to switch from Satisfatory early access to experimental.  
It also keeps the versions in seperate folders if set up that way.  

# Download
Download python  
Download this script from  
https://codeberg.org/marvin1099/SteamGameSwitcher/releases  
Or download this script from  
https://github.com/marvin1099/SteamGameSwitcher/releases  

# Install
Put the script in your /Steam/steamapps/ folder.  
There should be a lot of appmanifest files in there.  
At default the script will create a config for the Satisfatory versions.  
To make it work set your Satisfatory versions to experimental in Steam.  
Steam does not need to download the new files so close it then continue.  
Run the script, at this point you can switch gameversions by running the script.

# CustomGames
The script can be copyed and renamed to have a script for multiple games.  
To change the game open the 'SCRIPTNAME.json' file.  
of corse SCRIPTNAME needs to be the scriptname and the ' symbol is not in the filename.  
Next change the gamename to the new gamename.  
Next change the gameid to the new gameid.  
Next in gameversions you need to change/add the list like the following.  

    "versions" : [  
        ["HERE-FOLDER-END","HERE-GAME-VERSION"],  
        ["HERE-OTHERFOLDER-END","HERE-OTHERGAME-VERSION"],  
        ...   
        ["HERE-LASTFOLDER-END","HERE-LASTGAME-VERSION"]  
    ]  
You probably want the nomal version/first entry to have no additonal folder end.  
The script will always prefix the gamename in front of HERE-FOLDER-END.  

# Shortcut
You might want to make a shortcut for loding a specific version.  
Right click and click create a shortcut.  
On linux it says create a link to application.  
Point the shortcut to the script.   
In the argument field you can now and the index of your desired version.  
For other arguments see usage below.  

# Usage
    Use the following characters as arguments (only one can be used)
    Use 'h' for this help message and exit (whitout argumets this will also start help but will continue as if 's'was supplied)
    Use 's' to switch versions
    Eg.   script.py s    will switch versions
    Use 'r' to reverse switch versions
    Use any number it will use the corespondig version from the gameinfo dict
    Eg.   script.py 1    will start version experimental
    The script is now going to use 's' unless 'h' was used
    Exiting