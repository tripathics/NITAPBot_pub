import re
import discord
import os
import io
import asyncio
import csv
from dotenv import load_dotenv
from github import Github

# Load the .env file
load_dotenv()

# Datebase of students
students:dict = {}          # students[roll-no:str] = {name: str, email: str}
members:dict = {}           # members[userid:int] = {roll-no: int, guilds: [int,...]}

# Get the discord token from environment
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_PAT")

# get db from github repo
github = Github(GITHUB_TOKEN)
repo = github.get_user().get_repo('NITAPBot')

# Paths to database
path_sdb = 'students.csv'           # path to students database
path_mdb = 'members.csv'            # path to members database


intents = discord.Intents.default()
intents.members = True


class MyBot(discord.Client):
    async def on_ready(self):
        print(f'Logged in as {self.user}')

        # load the database
        loadDB()

    
    async def on_message(self, message:discord.Message):
        if (message.content and not message.author == self.user):
            print(f'Message from {message.author}: {message.content}')
            if (message.content == '$verify' and message.channel.name == 'membership-verification'):
                await membership_verification(bot=self, member=message.author)
        

    async def on_member_join(self, member:discord.Member):
        print(f'{member} joined {member.guild}')
        await membership_verification(self, member)

    # When a member leaves
    async def on_member_remove(self, member:discord.Member):
        # Check if the user left was actually a member of the guild or not
        if member.id in members:
            # The guild which the member left
            guild_left:discord.Guild = member.guild

            # Remove the guild from the database in user's field
            i = 0
            for in_guild in members[member.id]['guilds']:
                if (in_guild == guild_left.id):
                    members[member.id]['guilds'].pop(i)
                    break
                i+=1
            
            # remove the member from the list if their guilds list is empty
            if not len(members[member.id]['guilds']):
                members.pop(member.id)

            # update the database
            updateDB()
        
        # debug
        print('Members:')
        print(members)


# function to load data into dicts
def loadDB():
    # db files on github
    sdb = repo.get_contents(path_sdb)   # read only db
    mdb = repo.get_contents(path_mdb)   # rw db
    
    # load students from sdb
    sdb_iterable = sdb.decoded_content.decode().splitlines()
    reader = csv.DictReader(sdb_iterable)
    for row in reader:
        students[row.pop('roll-no')] = row
    print('Loaded: Students db')
    
    # load members from mdb
    mdb_iterable = mdb.decoded_content.decode().splitlines()
    reader = csv.DictReader(mdb_iterable)
    for row in reader:
        key = int(row['id'])
        data = {
            'roll-no': row['roll-no'],
            'guilds': [int(x) for x in row['guilds'].split(sep=',')]
        }
        members[key] = data
    print('Loaded: Members db')
    
    # debug
    print('members\n' + str(members))


def updateDB():    
    mdb = repo.get_contents(path_mdb)   # rw db

    # convert the dict into str
    out = io.StringIO()
    head = ['id', 'roll-no', 'guilds']
    writer = csv.DictWriter(out, head)
    
    writer.writeheader()

    for id, data in members.items():
        row = {
            'id': id,
            'roll-no': data['roll-no'],
            'guilds': ','.join(str(x) for x in data['guilds'])
        }
        writer.writerow(row)
    print(out.getvalue())
    
    # Content of updated file
    content = out.getvalue()

    # update the file and commit to repo
    repo.update_file(path_mdb, 'update members', content, mdb.sha)


# create channel to verify new-comers, interview them and finally give them channel membership 
async def membership_verification(bot:MyBot, member:discord.Member):
    guild_joined:discord.Guild = member.guild

    # Create a verification channel for that user
    async def create_verification_channel(member:discord.Member, guild:discord.Guild):
        # channel name
        ch_name:str = '\U0001F44B-verify-'+str(member).replace('#', '_')

        # Set permissions so that others can't see the channel
        overwrites = {
            guild_joined.default_role: discord.PermissionOverwrite(read_messages=False),
            guild_joined.me: discord.PermissionOverwrite(read_messages=True)            
        }

        # Create the channel inside welcome category
        category = discord.utils.get(guild.categories, name='welcome')
        channel:discord.TextChannel = await guild.create_text_channel(ch_name, overwrites=overwrites, category=category)

        # set permissions for new user to send and read messages
        perms = channel.overwrites_for(member)
        perms.read_messages=True
        perms.send_messages=True
        perms.read_message_history=True
        await channel.set_permissions(member, overwrite=perms)

        return channel

    verify_channel = await create_verification_channel(member, guild_joined)

    # Send a messages to the new channel
    async def verification(bot:discord.Client, verify_channel:discord.TextChannel, member:discord.Member):
        # Welcome message
        await asyncio.sleep(2.0)
        await verify_channel.send(f'Hello {member.mention} \U0001F44B! Welcome to NITAP 2020 Discord server!')
        await verify_channel.send('''Answer the questions strictly on basis of your college registration \U0000270D 
to avoid your membership application being rejected''')

        # ask questions
        questions = [
            ('name', 'What is your full name?'), 
            ('roll-no', 'Enter your roll no (like CSE/20/38)'), 
            ('email', 'Enter your college email id')
        ]
        
        answers = {}

        def check(a:discord.Message):
            return a.author == member and a.content and a.channel.name == '\U0001F44B-verify-'+str(a.author).replace('#', '_')

        regex = ['^[a-zA-Z0-9\s]+$', '^(CSE|ECE|ME|CE|EE)/20/[0-4][0-9]$', '^[A-Za-z0-9.]+[@]nitap.ac.in$']

        i = 0
        while i < 3:
            q = questions[i]
            await verify_channel.send(f'`{i+1}` {q[1]}')

            ans:discord.Message = await bot.wait_for('message', check=check)
            if not re.search(regex[i], ans.content):
                await ans.add_reaction('\U0001F44E')
            else:
                await ans.add_reaction('\U0001F440')
                answers[q[0]] = ans.content
                i += 1

        # Check the details in database
        if answers['roll-no'] in students:                                      # user entered valid roll no
            roll_no:str = answers['roll-no']

            # user having this roll no. already a member of the guild then don't allow the member to verify
            for m in [x[1] for x in members.items()]:
                if guild_joined.id in m['guilds'] and m['roll-no'] == roll_no:
                    return False

            if (students[roll_no]['name'] == answers['name'].strip().lower() and    # check if name and..
                students[roll_no]['email'] == answers['email']):                    # ..email match in the dict with key 'roll no'
                
                # Assign nickname to the new member
                first:str = answers['name'].split(sep=' ')[0]
                batch = answers['roll-no'].split(sep='/')
                last:str = batch[0] + batch[1]
                nick:str = first + '_' +last
                await member.edit(nick=nick)
                
                # add to members 
                if not member.id in members:                                        # if member is new to members
                    members[member.id] = {'roll-no': roll_no, 'guilds': []}
                members[member.id]['guilds'].append(guild_joined.id)

                # update db
                updateDB()

                return True
            else:
                return False
        else:
            return False

    # add member role upon successful verification
    if (await verification(bot, verify_channel, member)):
        # Add the member role
        member_role = discord.utils.get(guild_joined.roles, name='member')
        await member.add_roles(member_role)
        await verify_channel.send('Verification successful! You are now a member of the NITAP Discord Community \U0001F525')
        await asyncio.sleep(5.0)
    else:
        await verify_channel.send("Verification failed\U00002757 Contact the admin for further queries")
        await verify_channel.send("This channel will be deleted in a minute.")
        await asyncio.sleep(60.0)

    # delete the verification channel
    await verify_channel.delete()
    
    print('members:')
    print(members)
    

bot = MyBot(intents=intents)

bot.run(DISCORD_TOKEN)