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

import discord, voicelink, re

from io import StringIO
from discord import app_commands
from discord.ext import commands
from function import (
    settings,
    send,
    time as ctime,
    format_time,
    get_source,
    get_user,
    get_lang,
    truncate_string,
    cooldown_check,
    get_aliases,
    logger
)

from voicelink import SearchType, LoopType
from addons import LYRICS_PLATFORMS
from views import SearchView, ListView, LinkView, LyricsView, HelpView
from validators import url

async def nowplay(ctx: commands.Context, player: voicelink.Player):
    track = player.current
    if not track:
        return await send(ctx, 'noTrackPlaying', ephemeral=True)

    texts = await get_lang(ctx.guild.id, "nowplayingDesc", "nowplayingField", "nowplayingLink")
    upnext = "\n".join(f"`{index}.` `[{track.formatted_length}]` [{truncate_string(track.title)}]({track.uri})" for index, track in enumerate(player.queue.tracks()[:2], start=2))
    
    embed = discord.Embed(description=texts[0].format(track.title), color=settings.embed_color)
    embed.set_author(
        name=track.requester.display_name,
        icon_url=track.requester.display_avatar.url
    )
    embed.set_thumbnail(url=track.thumbnail)

    if upnext:
        embed.add_field(name=texts[1], value=upnext)

    pbar = "".join(":radio_button:" if i == round(player.position // round(track.length // 15)) else "▬" for i in range(15))
    icon = ":red_circle:" if track.is_stream else (":pause_button:" if player.is_paused else ":arrow_forward:")
    embed.add_field(name="\u2800", value=f"{icon} {pbar} **[{ctime(player.position)}/{track.formatted_length}]**", inline=False)

    return await send(ctx, embed, view=LinkView(texts[2].format(track.source.title()), track.emoji, track.uri))

class Basic(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.description = "Ta kategoria jest dostępna dla każdego na tym serwerze, niektóre komendy mogą wymagać głosowania."
        self.ctx_menu = app_commands.ContextMenu(
            name="play",
            callback=self._play
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    async def help_autocomplete(self, interaction: discord.Interaction, current: str) -> list:
        return [app_commands.Choice(name=c.capitalize(), value=c) for c in self.bot.cogs if c not in ["Nodes", "Task"] and current in c]

    async def play_autocomplete(self, interaction: discord.Interaction, current: str) -> list:
        if voicelink.pool.URL_REGEX.match(current):
            return []

        if current:
            node = voicelink.NodePool.get_node()
            if not node:
                return []
            tracks: list[voicelink.Track] = await node.get_tracks(current, requester=interaction.user, search_type=SearchType.SPOTIFY)
            return [app_commands.Choice(name=truncate_string(f"🎵 {track.author} - {track.title}", 100), value=truncate_string(f"{track.author} - {track.title}", 100)) for track in tracks] if tracks else []
        
        history = {track["identifier"]: track for track_id in reversed(await get_user(interaction.user.id, "history")) if (track := voicelink.decode(track_id))["uri"]}
        return [app_commands.Choice(name=truncate_string(f"🕒 {track['author']} - {track['title']}", 100), value=track['uri']) for track in history.values() if len(track['uri']) <= 100][:25]
            
    @commands.hybrid_command(name="connect", aliases=get_aliases("connect"))
    @app_commands.describe(channel="Podaj nazwę kanału do którego bot ma dołączyć.")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def connect(self, ctx: commands.Context, channel: discord.VoiceChannel = None) -> None:
        "Połącz bota do kanału głosowego"
        try:
            player = await voicelink.connect_channel(ctx, channel)
        except discord.errors.ClientException:
            return await send(ctx, "alreadyConnected")

        await send(ctx, 'connect', player.channel)
                
    @commands.hybrid_command(name="play", aliases=get_aliases("play"))
    @app_commands.describe(
        query="Podaj nazwę lub link do utworu.",
        start="Podaj czas od którego zacząć odtwarzanie, np. 1:00",
        end="Podaj czas do którego odtwarzać, np. 4:00"
    )
    @app_commands.autocomplete(query=play_autocomplete)
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def play(self, ctx: commands.Context, *, query: str, start: str = "0", end: str = "0") -> None:
        "Dodaj podany utwór na koniec kolejki."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(ctx)

        if not player.is_user_join(ctx.author):
            return await send(ctx, "notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)

        if ctx.interaction:
            await ctx.interaction.response.defer()

        tracks = await player.get_tracks(query, requester=ctx.author)
        if not tracks:
            return await send(ctx, "noTrackFound")

        try:
            if isinstance(tracks, voicelink.Playlist):
                index = await player.add_track(tracks.tracks, start_time=format_time(start), end_time=format_time(end))
                await send(ctx, "playlistLoad", tracks.name, index)
            else:
                position = await player.add_track(tracks[0], start_time=format_time(start), end_time=format_time(end))
                texts = await get_lang(ctx.guild.id, "live", "trackLoad_pos", "trackLoad")

                stream_content = f"`{texts[0]}`" if tracks[0].is_stream else ""
                additional_content = texts[1] if position >= 1 and player.is_playing else texts[2]

                await send(
                    ctx,
                    stream_content + additional_content,
                    tracks[0].title, tracks[0].uri, tracks[0].author, tracks[0].formatted_length,
                    position if position >= 1 and player.is_playing else None
                )
        finally:
            if not player.is_playing:
                await player.do_next()
    
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def _play(self, interaction: discord.Interaction, message: discord.Message):
        query = ""

        if message.content:
            url = re.findall(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+", message.content)
            if url:
                query = url[0]

        elif message.attachments:
            query = message.attachments[0].url

        if not query:
            return await send(interaction, "noPlaySource", ephemeral=True)

        player: voicelink.Player = interaction.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(interaction)

        if not player.is_user_join(interaction.user):
            return await send(interaction, "notInChannel", interaction.user.mention, player.channel.mention, ephemeral=True)

        await interaction.response.defer()
        tracks = await player.get_tracks(query, requester=interaction.user)
        if not tracks:
            return await send(interaction, "noTrackFound")

        try:
            if isinstance(tracks, voicelink.Playlist):
                index = await player.add_track(tracks.tracks)
                await send(interaction, "playlistLoad", tracks.name, index)
            else:
                position = await player.add_track(tracks[0])
                texts = await get_lang(interaction.guild.id, "live", "trackLoad_pos", "trackLoad")

                stream_content = f"`{texts[0]}`" if tracks[0].is_stream else ""
                additional_content = texts[1] if position >= 1 and player.is_playing else texts[2]

                await send(
                    interaction,
                    stream_content + additional_content,
                    tracks[0].title, tracks[0].uri, tracks[0].author, tracks[0].formatted_length,
                    position if position >= 1 and player.is_playing else None
                )
        finally:
            if not player.is_playing:
                await player.do_next()

    @commands.hybrid_command(name="search", aliases=get_aliases("search"))
    @app_commands.describe(
        query="Podaj nazwę utworu.",
        platform="Wybierz platformę na której chcesz wyszukać podany utwór."
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name=search_type.display_name, value=search_type.name)
        for search_type in SearchType
    ])
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def search(self, ctx: commands.Context, *, query: str, platform: str = SearchType.YOUTUBE.name):
        "Wyszukaj utwory po tytule."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(ctx)

        if not player.is_user_join(ctx.author):
            return await send(ctx, "notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)

        if url(query):
            return await send(ctx, "noLinkSupport", ephemeral=True)
        
        search_type: SearchType = SearchType.match(platform) or SearchType.YOUTUBE
        tracks = await player.get_tracks(query=query, requester=ctx.author, search_type=search_type)
        if not tracks:
            return await send(ctx, "noTrackFound")

        texts = await get_lang(ctx.guild.id, "searchTitle", "searchDesc", "live", "trackLoad_pos", "trackLoad", "searchWait", "searchSuccess")
        query_track = "\n".join(f"`{index}.` `[{track.formatted_length}]` **{track.title[:35]}**" for index, track in enumerate(tracks[0:10], start=1))
        embed = discord.Embed(title=texts[0].format(query), description=texts[1].format(get_source(search_type.display_name, "emoji"), search_type.display_name, len(tracks[0:10]), query_track), color=settings.embed_color)
        view = SearchView(tracks=tracks[0:10], texts=[texts[5], texts[6]])
        view.response = await send(ctx, embed, view=view, ephemeral=True)

        await view.wait()
        if view.values is not None:
            msg = ""
            for value in view.values:
                track = tracks[int(value.split(". ")[0]) - 1]
                position = await player.add_track(track)
                msg += (f"`{texts[2]}`" if track.is_stream else "") + (texts[3].format(track.title, track.uri, track.author, track.formatted_length, position) if position >= 1 else texts[4].format(track.title, track.uri, track.author, track.formatted_length))
            await send(ctx, msg)

            if not player.is_playing:
                await player.do_next()

    @commands.hybrid_command(name="playtop", aliases=get_aliases("playtop"))
    @app_commands.describe(
        query="Podaj nazwę lub link do utworu.",
        start="Podaj czas od którego zacząć odtwarzanie, np. 1:00",
        end="Podaj czas do którego odtwarzać, np. 4:00"
    )
    @app_commands.autocomplete(query=play_autocomplete)
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def playtop(self, ctx: commands.Context, *, query: str, start: str = "0", end: str = "0"):
        "Dodaj podany utwór na początek kolejki."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(ctx)

        if not player.is_user_join(ctx.author):
            return await send(ctx, "notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)
        
        if ctx.interaction:
            await ctx.interaction.response.defer()

        tracks = await player.get_tracks(query, requester=ctx.author)
        if not tracks:
            return await send(ctx, "noTrackFound")
        
        try:
            if isinstance(tracks, voicelink.Playlist):
                index = await player.add_track(tracks.tracks, start_time=format_time(start), end_time=format_time(end), at_front=True)
                await send(ctx, "playlistLoad", tracks.name, index)
            else:
                position = await player.add_track(tracks[0], start_time=format_time(start), end_time=format_time(end), at_front=True)
                texts = await get_lang(ctx.guild.id, "live", "trackLoad_pos", "trackLoad")

                stream_content = f"`{texts[0]}`" if tracks[0].is_stream else ""
                additional_content = texts[1] if position >= 1 and player.is_playing else texts[2]

                await send(
                    ctx,
                    stream_content + additional_content,
                    tracks[0].title, tracks[0].uri, tracks[0].author, tracks[0].formatted_length,
                    position if position >= 1 and player.is_playing else None
                )
        finally:
            if not player.is_playing:
                await player.do_next()

    @commands.hybrid_command(name="forceplay", aliases=get_aliases("forceplay"))
    @app_commands.describe(
        query="Podaj nazwę lub link do utworu.",
        start="Podaj czas od którego zacząć odtwarzanie, np. 1:00",
        end="Podaj czas do którego odtwarzać, np. 4:00"
    )
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def forceplay(self, ctx: commands.Context, *, query: str, start: str = "0", end: str = "0"):
        "Wymuś natychmiastowe odtwarzanie podanego utworu."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(ctx)

        if not player.is_privileged(ctx.author):
            return await send(ctx, "missingPerms_function", ephemeral=True)
        
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        tracks = await player.get_tracks(query, requester=ctx.author)
        if not tracks:
            return await send(ctx, "noTrackFound")
        
        try:
            if isinstance(tracks, voicelink.Playlist):
                index = await player.add_track(tracks.tracks, start_time=format_time(start), end_time=format_time(end), at_front=True)
                await send(ctx, "playlistLoad", tracks.name, index)
            else:
                texts = await get_lang(ctx.guild.id, "live", "trackLoad")
                await player.add_track(tracks[0], start_time=format_time(start), end_time=format_time(end), at_front=True)

                stream_content = f"`{texts[0]}`" if tracks[0].is_stream else ""

                await send(
                    ctx,
                    stream_content + texts[1],
                    tracks[0].title, tracks[0].uri, tracks[0].author, tracks[0].formatted_length,
                )
        finally:
            if player.queue._repeat.mode == voicelink.LoopType.TRACK:
                await player.set_repeat(voicelink.LoopType.OFF)
                
            await player.stop() if player.is_playing else await player.do_next()

    @commands.hybrid_command(name="pause", aliases=get_aliases("pause"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def pause(self, ctx: commands.Context):
        "Zapauzuj odtwarzanie."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if player.is_paused:
            return await send(ctx, "pauseError", ephemeral=True)

        if not player.is_privileged(ctx.author):
            if ctx.author in player.pause_votes:
                return await send(ctx, "voted", ephemeral=True)
            
            player.pause_votes.add(ctx.author)
            if len(player.pause_votes) < (required := player.required()):
                return await send(ctx, "pauseVote", ctx.author, len(player.pause_votes), required)

        await player.set_pause(True, ctx.author)
        await send(ctx, "paused", ctx.author)

    @commands.hybrid_command(name="resume", aliases=get_aliases("resume"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def resume(self, ctx: commands.Context):
        "Wznów odtwarzanie."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_paused:
            return await send(ctx, "resumeError")

        if not player.is_privileged(ctx.author):
            if ctx.author in player.resume_votes:
                return await send(ctx, "voted", ephemeral=True)
            
            player.resume_votes.add(ctx.author)
            if len(player.resume_votes) < (required := player.required()):
                return await send(ctx, "resumeVote", ctx.author, len(player.resume_votes), required)

        await player.set_pause(False, ctx.author)
        await send(ctx, "resumed", ctx.author)

    @commands.hybrid_command(name="skip", aliases=get_aliases("skip"))
    @app_commands.describe(index="Podaj numer utworu do którego chcesz pominąć.")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def skip(self, ctx: commands.Context, index: int = 0):
        "Pomiń do następnego utworu lub do konkretnej pozycji w kolejce."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.node._available:
            return await send(ctx, "nodeReconnect")
        
        if not player.is_playing:
            return await send(ctx, "skipError", ephemeral=True)

        if not player.is_privileged(ctx.author):
            if ctx.author == player.current.requester:
                pass
            elif ctx.author in player.skip_votes:
                return await send(ctx, "voted", ephemeral=True)
            else:
                player.skip_votes.add(ctx.author)
                if len(player.skip_votes) < (required := player.required()):
                    return await send(ctx, "skipVote", ctx.author, len(player.skip_votes), required)

        if index:
            player.queue.skipto(index)

        await send(ctx, "skipped", ctx.author)
        if player.queue._repeat.mode == voicelink.LoopType.TRACK:
            await player.set_repeat(voicelink.LoopType.OFF)
            
        await player.stop()

    @commands.hybrid_command(name="back", aliases=get_aliases("back"))
    @app_commands.describe(index="Podaj indeks utworu do którego chcesz cofnąć.")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def back(self, ctx: commands.Context, index: int = 1):
        "Cofnij do poprzedniego utworu lub do konkretnej poprzedniej pozycji w kolejce."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.node._available:
            return await send(ctx, "nodeReconnectode")
        
        if not player.is_privileged(ctx.author):
            if ctx.author in player.previous_votes:
                return await send(ctx, "voted", ephemeral=True)
            
            player.previous_votes.add(ctx.author)
            if len(player.previous_votes) < (required := player.required()):
                return await send(ctx, "backVote", ctx.author, len(player.previous_votes), required)

        if not player.is_playing:
            player.queue.backto(index)
            await player.do_next()
        else:
            player.queue.backto(index + 1)
            await player.stop()

        await send(ctx, "backed", ctx.author)
        if player.queue._repeat.mode == voicelink.LoopType.TRACK:
            await player.set_repeat(voicelink.LoopType.OFF)

    @commands.hybrid_command(name="seek", aliases=get_aliases("seek"))
    @app_commands.describe(position="Input position. Exmaple: 1:20.")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def seek(self, ctx: commands.Context, position: str):
        "Zmień pozycje odtwarzania utworu (czas)."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send(ctx, "missingPerms_pos", ephemeral=True)

        if not player.current or player.position == 0:
            return await send(ctx, "noTrackPlaying", ephemeral=True)

        if not (num := format_time(position)):
            return await send(ctx, "timeFormatError", ephemeral=True)

        await player.seek(num, ctx.author)
        await send(ctx, "seek", position)

    @commands.hybrid_group(
        name="queue", 
        aliases=get_aliases("queue"),
        fallback="list",
        invoke_without_command=True
    )
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def queue(self, ctx: commands.Context):
        "Wyświetl utwory znajdujące się w kolejce odtwarzania."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_user_join(ctx.author):
            return await send(ctx, "notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)

        if player.queue.is_empty:
            return await nowplay(ctx, player)
        view = ListView(player=player, author=ctx.author)
        view.response = await send(ctx, await view.build_embed(), view=view)

    @queue.command(name="export", aliases=get_aliases("export"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def export(self, ctx: commands.Context):
        "Wyeksportuj całą kolejkę do pliku."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)
        
        if not player.is_user_join(ctx.author):
            return await send(ctx, "notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)
        
        if player.queue.is_empty and not player.current:
            return await send(ctx, "noTrackPlaying", ephemeral=True)

        await ctx.defer()

        tracks = player.queue.tracks(True)
        temp = ""
        raw = "------->Surowe informacje<-------\n"

        total_length = 0
        for index, track in enumerate(tracks, start=1):
            temp += f"{index}. {track.title} [{ctime(track.length)}]\n"
            raw += track.track_id
            if index != len(tracks):
                raw += ","
            total_length += track.length

        temp = "!Pamiętaj by nie modyfikować tego pliku!\n------------->Informacje<-------------\nSerwer: {} ({})\nNa żądanie: {} ({})\nUtwory: {} - {}\n------------>Utwory<------------\n".format(
            ctx.guild.name, ctx.guild.id,
            ctx.author.display_name, ctx.author.id,
            len(tracks), ctime(total_length)
        ) + temp
        temp += raw

        await ctx.reply(content="", file=discord.File(StringIO(temp), filename=f"{ctx.guild.id}_Full_Queue.txt"))

    @queue.command(name="import", aliases=get_aliases("import"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def _import(self, ctx: commands.Context, attachment: discord.Attachment):
        "Zaimportuj utwory z pliku i dodaj je do kolejki."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            player = await voicelink.connect_channel(ctx)

        if not player.is_user_join(ctx.author):
            return await send(ctx, "notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)

        try:
            bytes = await attachment.read()
            track_ids = bytes.split(b"\n")[-1]
            track_ids = track_ids.decode().split(",")
            
            tracks = [voicelink.Track(track_id=track_id, info=voicelink.decode(track_id), requester=ctx.author) for track_id in track_ids]
            if not tracks:
                return await send(ctx, "noTrackFound")

            index = await player.add_track(tracks)
            await send(ctx, "playlistLoad", attachment.filename, index)
        except Exception as e:
            logger.error("error", exc_info=e)
            raise e

        finally:
            if not player.is_playing:
                await player.do_next()

    @commands.hybrid_command(name="history", aliases=get_aliases("history"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def history(self, ctx: commands.Context):
        "Wyświetl historię kolejki (utowry które już były odtworzone)."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_user_join(ctx.author):
            return await send(ctx, "notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)

        if not player.queue.history():
            return await nowplay(ctx, player)

        view = ListView(player=player, author=ctx.author, is_queue=False)
        view.response = await send(ctx, await view.build_embed(), view=view)

    @commands.hybrid_command(name="leave", aliases=get_aliases("leave"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def leave(self, ctx: commands.Context):
        "Rozłącz bota z kanału głosowego i wyczyść jego koejkę odtwarzania."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            if ctx.author in player.stop_votes:
                return await send(ctx, "voted", ephemeral=True)
            else:
                player.stop_votes.add(ctx.author)
                if len(player.stop_votes) >= (required := player.required(leave=True)):
                    pass
                else:
                    return await send(ctx, "leaveVote", ctx.author, len(player.stop_votes), required)

        await send(ctx, "left", ctx.author)
        await player.teardown()

    @commands.hybrid_command(name="nowplaying", aliases=get_aliases("nowplaying"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def nowplaying(self, ctx: commands.Context):
        "Zobacz szczegóły o odtwarzanej obecnie piosence."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_user_join(ctx.author):
            return await send(ctx, "notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)

        await nowplay(ctx, player)

    @commands.hybrid_command(name="loop", aliases=get_aliases("loop"))
    @app_commands.describe(mode="Wybierz tryb pętli.")
    @app_commands.choices(mode=[
        app_commands.Choice(name=loop_type.name.title(), value=loop_type.name)
        for loop_type in LoopType
    ])
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def loop(self, ctx: commands.Context, mode: str):
        "Zmień tryb pętli."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send(ctx, "missingPerms_mode", ephemeral=True)

        await player.set_repeat(LoopType[mode] if mode in LoopType.__members__ else LoopType.OFF, ctx.author)
        await send(ctx, "repeat", mode.capitalize())

    @commands.hybrid_command(name="clear", aliases=get_aliases("clear"))
    @app_commands.describe(queue="Wybierz co chesz wyczyścić.")
    @app_commands.choices(queue=[
        app_commands.Choice(name='Kolejka', value='queue'),
        app_commands.Choice(name='Historia kolejki', value='history')
    ])
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def clear(self, ctx: commands.Context, queue: str = "queue"):
        "Usuń wszystkie pozycje z kolejki i jej historii."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send(ctx, "missingPerms_queue", ephemeral=True)

        await player.clear_queue(queue, ctx.author)
        await send(ctx, "cleared", queue.capitalize())

    @commands.hybrid_command(name="remove", aliases=get_aliases("remove"))
    @app_commands.describe(
        position1="Podaj pozycję z kolejki, którą chcesz usunąć.",
        position2="Podaj zakres kolejki, który chcesz usunąć.",
        member="Usuń pozycje z kolejki dodane przez konkretnego użytkownika."
    )
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def remove(self, ctx: commands.Context, position1: int, position2: int = None, member: discord.Member = None):
        "Usuń konkretną pozycję lub zakres pozycji z kolejki."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send(ctx, "missingPerms_queue", ephemeral=True)

        removed_tracks = await player.remove_track(position1, position2, remove_target=member, requester=ctx.author)
        await send(ctx, "removed", len(removed_tracks.keys()))

    @commands.hybrid_command(name="forward", aliases=get_aliases("forward"))
    @app_commands.describe(position="Podaj ilość czasu o jaką chcesz przewinąć do przodu. np. 1:20")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def forward(self, ctx: commands.Context, position: str = "10"):
        "Przewiń utwór do przodu o podany czas. Domyślnie jest to 10 sekund."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send(ctx, "missingPerms_pos", ephemeral=True)

        if not player.current:
            return await send(ctx, "noTrackPlaying", ephemeral=True)

        if not (num := format_time(position)):
            return await send(ctx, "timeFormatError", ephemeral=True)

        await player.seek(int(player.position + num))
        await send(ctx, "forward", ctime(player.position + num))

    @commands.hybrid_command(name="rewind", aliases=get_aliases("rewind"))
    @app_commands.describe(position="Podaj ilość czasu o jaką chcesz przewinąć do tyłu. Przykład: 1:20")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def rewind(self, ctx: commands.Context, position: str = "10"):
        "Przewiń utwór do tyłu o podany czas. Domyślnie jest to 10 sekund."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send(ctx, "missingPerms_pos", ephemeral=True)

        if not player.current:
            return await send(ctx, "noTrackPlaying", ephemeral=True)
        
        if not (num := format_time(position)):
            return await send(ctx, "timeFormatError", ephemeral=True)

        await player.seek(int(player.position - num))
        await send(ctx, "rewind", ctime(player.position - num))

    @commands.hybrid_command(name="replay", aliases=get_aliases("replay"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def replay(self, ctx: commands.Context):
        "Zresetuj postęp w odtwarzaniu obecnego utworu (cofnij do początku)."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send(ctx, "missingPerms_pos", ephemeral=True)

        if not player.current:
            return await send(ctx, "noTrackPlaying", ephemeral=True)
        
        await player.seek(0)
        await send(ctx, "replay")

    @commands.hybrid_command(name="shuffle", aliases=get_aliases("shuffle"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def shuffle(self, ctx: commands.Context):
        "Wymieszaj kolejność odtwarzania w kolejce (nie można cofnąć)."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            if ctx.author in player.shuffle_votes:
                return await send(ctx, "voted", ephemeral=True)
            
            player.shuffle_votes.add(ctx.author)
            if len(player.shuffle_votes) < (required := player.required()):
                return await send(ctx, "shuffleVote", ctx.author, len(player.shuffle_votes), required)
        
        await player.shuffle("queue", ctx.author)
        await send(ctx, "shuffled")

    @commands.hybrid_command(name="swap", aliases=get_aliases("swap"))
    @app_commands.describe(
        position1="Utwór do zamiany. Przykład: 2",
        position2="Utwór do zamiany z pozycją 1. Przykład: 1"
    )
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def swap(self, ctx: commands.Context, position1: int, position2: int):
        "Zamień pozycję dwóch podanych pozycji w kolejce."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send(ctx, "missingPerms_pos", ephemeral=True)

        track1, track2 = await player.swap_track(position1, position2, ctx.author)        
        await send(ctx, "swapped", track1.title, track2.title)

    @commands.hybrid_command(name="move", aliases=get_aliases("move"))
    @app_commands.describe(
        target="Utwór do przesunięcia. Przykład: 2",
        to="Nowa pozycja na którą przenieść utwór. Przykład: 1"
    )
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def move(self, ctx: commands.Context, target: int, to: int):
        "Przesuń utwór na konkretną pozycję w kolejce."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)
        
        if not player.is_privileged(ctx.author):
            return await send(ctx, "missingPerms_pos", ephemeral=True)

        moved_track = await player.move_track(target, to, ctx.author)
        await send(ctx, "moved", moved_track, to)

    @commands.hybrid_command(name="lyrics", aliases=get_aliases("lyrics"))
    @app_commands.describe(title="Wyszukuje twoje zapytanie i wyświetla znalezione słowa utworu.")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def lyrics(self, ctx: commands.Context, title: str = "", artist: str = ""):
        "Wyświetl słowa podanego utworu (Genius)"
        if not title:
            player: voicelink.Player = ctx.guild.voice_client
            if not player or not player.is_playing:
                return await send(ctx, "noTrackPlaying", ephemeral=True)
            
            title = player.current.title
            artist = player.current.author
        
        await ctx.defer()
        lyrics_platform = LYRICS_PLATFORMS.get(settings.lyrics_platform)
        if lyrics_platform:
            lyrics = await lyrics_platform().get_lyrics(title, artist)
            if not lyrics:
                return await send(ctx, "lyricsNotFound", ephemeral=True)
            
            view = LyricsView(name=title, source={_: re.findall(r'.*\n(?:.*\n){,22}', v or "") for _, v in lyrics.items()}, author=ctx.author)
            view.response = await send(ctx, view.build_embed(), view=view)

    @commands.hybrid_command(name="swapdj", aliases=get_aliases("swapdj"))
    @app_commands.describe(member="Wybierz użytkownika, któremu przekazana zostanie rola DJ'a")
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def swapdj(self, ctx: commands.Context, member: discord.Member):
        "Przekaż rolę DJ'a."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_user_join(ctx.author):
            return await send(ctx, "notInChannel", ctx.author.mention, player.channel.mention, ephemeral=True)

        if player.dj.id != ctx.author.id or player.settings.get('dj', False):
            return await send(ctx, "notdj", f"<@&{player.settings['dj']}>" if player.settings.get('dj') else player.dj.mention, ephemeral=True)

        if player.dj.id == member.id or member.bot:
            return await send(ctx, "djToMe", ephemeral=True)

        if member not in player.channel.members:
            return await send(ctx, "djnotinchannel", member, ephemeral=True)

        player.dj = member
        await send(ctx, "djswap", member)

    @commands.hybrid_command(name="autoplay", aliases=get_aliases("autoplay"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def autoplay(self, ctx: commands.Context):
        "Przełącz tryb autoodtwarzania, podobne utowry zostaną dodane do kolejki po jej skończeniu się."
        player: voicelink.Player = ctx.guild.voice_client
        if not player:
            return await send(ctx, "noPlayer", ephemeral=True)

        if not player.is_privileged(ctx.author):
            return await send(ctx, "missingPerms_autoplay", ephemeral=True)

        check = not player.settings.get("autoplay", False)
        player.settings['autoplay'] = check
        await send(ctx, "autoplay", await get_lang(ctx.guild.id, "enabled" if check else "disabled"))

        if not player.is_playing:
            await player.do_next()
        
        if player.is_ipc_connected:
            await player.send_ws({"op": "toggleAutoplay", "status": check})

    @commands.hybrid_command(name="help", aliases=get_aliases("help"))
    @app_commands.autocomplete(category=help_autocomplete)
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def help(self, ctx: commands.Context, category: str = "News") -> None:
        "Wyświetl wszystkie dostępne komendy."
        if category not in self.bot.cogs:
            category = "News"
        view = HelpView(self.bot, ctx.author)
        embed = view.build_embed(category)
        view.response = await send(ctx, embed, view=view)

    @commands.hybrid_command(name="ping", aliases=get_aliases("ping"))
    @commands.dynamic_cooldown(cooldown_check, commands.BucketType.guild)
    async def ping(self, ctx: commands.Context):
        "Sprawdź czy bot żyje, oraz jakie ma opóźnienie."
        player: voicelink.Player = ctx.guild.voice_client

        value = await get_lang(ctx.guild.id, "pingTitle1", "pingfield1", "pingTitle2", "pingfield2")
        
        embed = discord.Embed(color=settings.embed_color)
        embed.add_field(
            name=value[0],
            value=value[1].format(
                "0", "0", self.bot.latency, '😭' if self.bot.latency > 5 else ('😨' if self.bot.latency > 1 else '👌'), "St Louis, MO, United States"
        ))

        if player:
            embed.add_field(
                name=value[2],
                value=value[3].format(
                    player.node._identifier, player.ping, player.node.player_count, player.channel.rtc_region),
                    inline=False
            )

        await send(ctx, embed)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Basic(bot))