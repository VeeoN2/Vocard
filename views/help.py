"""MIT License

Copyright (c) 2023 - present Vocard Development

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import discord
from discord.ext import commands

import function as func

class HelpDropdown(discord.ui.Select):
    def __init__(self, categories:list):
        self.view: HelpView

        super().__init__(
            placeholder="Wybierz kategorię:",
            min_values=1, max_values=1,
            options=[
                discord.SelectOption(emoji="🆕", label="Opis", description="Opis bota."),
                discord.SelectOption(emoji="🕹️", label="Tutorial", description="Jak używać bota."),
            ] + [
                discord.SelectOption(emoji=emoji, label=f"{category}", description=f"Komendy z kategorii: {category.lower()}.")
                for category, emoji in zip(categories, ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"])
            ],
            custom_id="select"
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        embed = self.view.build_embed(self.values[0].split(" ")[0])
        await interaction.response.edit_message(embed=embed)

class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author: discord.Member) -> None:
        super().__init__(timeout=60)

        self.author: discord.Member = author
        self.bot: commands.Bot = bot
        self.response: discord.Message = None
        self.categories: list[str] = [ name.capitalize() for name, cog in bot.cogs.items() if len([c for c in cog.walk_commands()]) ]

        self.add_item(discord.ui.Button(label='Pomoc', emoji=':support:915152950471581696', url='https://discord.com/users/406859750375030784'))
#        self.add_item(discord.ui.Button(label='Invite', emoji=':invite:915152589056790589', url='https://discord.com/api/oauth2/authorize?client_id=1191483380332761248&permissions=8&scope=bot+applications.commands'.format(func.tokens.client_id)))
        self.add_item(discord.ui.Button(label='Github', emoji=':github:1098265017268322406', url='https://github.com/VeeoN2/Vocard/tree/full_polish'))
#        self.add_item(discord.ui.Button(label='Donate', emoji=':patreon:913397909024800878', url='https://www.patreon.com/Vocard'))
        self.add_item(HelpDropdown(self.categorys))
    
    async def on_error(self, error, item, interaction) -> None:
        return

    async def on_timeout(self) -> None:
        for child in self.children:
            if child.custom_id == "select":
                child.disabled = True
        try:
            await self.response.edit(view=self)
        except:
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> None:
        return interaction.user == self.author

    def build_embed(self, category: str) -> discord.Embed:
        category = category.lower()
        if category == "news":
            embed = discord.Embed(title="Pomoc RADIO PUBLIC ++", url="https://discord.com/users/406859750375030784", color=func.settings.embed_color)
            embed.add_field(
                name=f"Dostępne kategorie: [{2 + len(self.categorys)}]",
                value="```py\n👉 Informacje\n2. Poradnik\n{}```".format("".join(f"{i}. {c}\n" for i, c in enumerate(self.categorys, start=3))),
                inline=True
            )

            update = "RADIO PUBLIC ++ to bot muzyczny bazowany na projekcie Vocard.\n\n Posiada wygodny panel kontrolny www (radio.veeon.pl) oraz obsługuje linki z YouTube, Spotify, Soundcloud, Twitch.\n\n Tłumaczniem na język polski oraz hostowaniem zajmuje się @veeon__ (zgłaszaj błedy)."
            embed.add_field(name="📰 Informacje:", value=update, inline=True)
            embed.add_field(name="Zacznij używać bota", value="```Dołącz do kanału głosowego i użyj /play {Nazwa/URL}. Wspierane są: Tytuły, Linki do video oraz playlist Youtube lub linki z Spotify```", inline=False)
            
            return embed

        embed = discord.Embed(title=f"Kategoria: {category.capitalize()}", color=func.settings.embed_color)
        embed.add_field(name=f"Kategorie: [{2 + len(self.categorys)}]", value="```py\n" + "\n".join(("👉 " if c == category.capitalize() else f"{i}. ") + c for i, c in enumerate(['Informacje', 'Poradnik'] + self.categorys, start=1)) + "```", inline=True)

        if category == 'tutorial':
            embed.description = "Jak używać bota? Podstawowa obsługa pokazana została w filmiku poniżej."
            embed.set_image(url="https://cdn.discordapp.com/attachments/674788144931012638/917656288899514388/final_61aef3aa7836890135c6010c_669380.gif")
        else:
            cog = [c for _, c in self.bot.cogs.items() if _.lower() == category][0]

            commands = [command for command in cog.walk_commands()]
            embed.description = cog.description
            embed.add_field(
                name=f"{category} - komendy: [{len(commands)}]",
                value="```{}```".format("".join(f"/{command.qualified_name}\n" for command in commands if not command.qualified_name == cog.qualified_name))
            )

        return embed