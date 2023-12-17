# SteamGameSwitcher
Main Repo: https://codeberg.org/marvin1099/SteamGameSwitcher  
Backup Repo: https://github.com/marvin1099/SteamGameSwitcher  

# Table of contents
- [Description](#description)  
- [Download](#download)  
- [Install](#install)  
- [CustomGames](#customgames)  
- [Shortcut](#shortcut)  
- [Usage](#usage)  
- [Examples](#examples)
  
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
Make shure you have steamcmd installed and in your system path vars.
Run the script, at this point you can switch gameversions by running the script.

# CustomGames
The script can be copyed and renamed to have a script for multiple games.  
So for the game Portal you might use the name SGS-Portal.py.  
The portal id is 400 so you need to replace GAMEID in ./SGS-Portal.py id GAMEID:  
So run the script like this

    ./SGS-Portal.py id 400
To change any settings open the 'SCRIPTNAME.txt' file.  
Of course SCRIPTNAME needs to be the scriptname and the ' symbol is not in the filename.   
You for example you can cange the folder that is used for a beta,  
by editing the shortver section

    "shortver"
    {
	    ""		"" 
    }
The first on the left "" is the pulic version entry and allways exsists.  
Here you can change the right to change the Folder prefix.  
So on the example portal "PUPLIC" on the right will result in the folder PortalPUPLIC.  

# Shortcut
You might want to make a shortcut for loding a specific version.  
Right click and click create a shortcut.  
On linux it says create a link to application.  
Point the shortcut to the script.   
In the argument field you can now and the index of your desired version.  
For other arguments see usage below.  

# Usage
    h               To display this help and exit
    id GAMEID       To set the game (id) the script uses
    VERSION         Valid values are
                        0 to circle (default), - to reverse circle
                        INDEX to select a index (eg 2 gets branch 2, -2 gets 2end last)
                        NAME to select name (eg '' for public or experimental for experimental)

# Examples
    ./SGS.py 0
will circle all branches

    ./SGS.py ""
will select the public branch

