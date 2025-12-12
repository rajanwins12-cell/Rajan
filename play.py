from pyrogram import Client, filters

@Client.on_message(filters.command('play'))
async def play(_, message):
    await message.reply("Playing song… (demo)")