import os
import asyncio
import discord
from discord.ext import commands
from discord.ui import View, Button
from typing import Dict, Optional, Set, List

#============================================================

#INTENTS E PREFIXO

#============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

#============================================================

#CONFIGURAÇÕES GLOBAIS (DICIONÁRIO EM MEMÓRIA)

#============================================================

config: Dict[str, Optional[str]] = {
"logo": None,         # URL da thumbnail do embed principal
"banner": None,       # URL da imagem grande do embed principal
"canal_apostado": None,  # ID do canal onde o comando !apostado pode ser usado (ou None para qualquer)
"categoria_salas": None, # Nome da categoria onde as salas serão criadas
"canal_logs": None,   # ID do canal de logs
"canal_antispam": None,  # ID do canal onde o anti-spam atua
"qr_code": None       # URL da imagem do QR Code para pagamento
}

#============================================================

#ESTRUTURAS PARA CONTROLE DE PARTIDAS E ANTI-SPAM

#============================================================

#Chave: (guild_id, message_id) → View ativa

active_views: Dict[tuple, 'ApostadoView'] = {}

#Anti-spam: (guild_id, user_id, channel_id) → últimas mensagens (lista de conteúdos)

spam_tracker: Dict[tuple, List[str]] = {}

#============================================================

#FUNÇÕES AUXILIARES

#============================================================

async def enviar_log(guild: discord.Guild, mensagem: str, cor: discord.Color = discord.Color.blue()):
    """Envia uma embed de log no canal configurado."""
    canal_id = config["canal_logs"]
    if canal_id:
        canal = guild.get_channel(int(canal_id))
        if canal:
            embed = discord.Embed(description=mensagem, color=cor)
            embed.set_footer(text="Sistema de Logs")
            await canal.send(embed=embed)

def embed_base(titulo: str, descricao: str, cor: discord.Color) -> discord.Embed:
    """Cria um embed padronizado."""
    embed = discord.Embed(title=titulo, description=descricao, color=cor)
    embed.set_footer(text="Org Apostado • Sistema Profissional")
    return embed

#============================================================

#VIEW PRINCIPAL DOS APOSTADOS

#============================================================

class ApostadoView(View):
    def __init__(self, modo: str, valor: str, premio: str, guild: discord.Guild):
        super().__init__(timeout=None)
        self.modo = modo
        self.valor = valor
        self.premio = premio
        self.guild = guild
        self.participants = set()
        self.user_channels = {}
        self.user_voice_channels = {}

# -----------------------------------------------  
# BOTÃO 🟢 JOGAR  
# -----------------------------------------------  
@discord.ui.button(label="Jogar", style=discord.ButtonStyle.green, custom_id="apostado_jogar")  
async def jogar(self, interaction: discord.Interaction, button: Button):  
    user = interaction.user  

    # Impedir dupla entrada  
    if user.id in self.participants:  
        embed = embed_base("❌ Erro", "Você já está na partida!", discord.Color.red())  
        await interaction.response.send_message(embed=embed, ephemeral=True)  
        return  

    # Criar categoria se configurada  
    categoria = None  
    if config["categoria_salas"]:  
        categoria = discord.utils.get(self.guild.categories, name=config["categoria_salas"])  
        if not categoria:  
            # Tenta criar a categoria automaticamente (requer permissões)  
            try:  
                categoria = await self.guild.create_category(config["categoria_salas"])  
            except discord.Forbidden:  
                pass  

    # Permissões para o canal privado  
    overwrites = {  
        self.guild.default_role: discord.PermissionOverwrite(read_messages=False),  
        self.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),  
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True)  
    }  
    # Adiciona permissão para todos os administradores  
    for role in self.guild.roles:  
        if role.permissions.administrator:  
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)  

    channel_name = f"apostado-{user.name}".replace(" ", "-").lower()  

    try:  
        if categoria:  
            texto = await self.guild.create_text_channel(channel_name, overwrites=overwrites, category=categoria)  
            voz = await self.guild.create_voice_channel(channel_name, overwrites=overwrites, category=categoria)  
        else:  
            texto = await self.guild.create_text_channel(channel_name, overwrites=overwrites)  
            voz = await self.guild.create_voice_channel(channel_name, overwrites=overwrites)  
    except discord.Forbidden:  
        embed = embed_base("❌ Erro", "Não tenho permissão para criar canais. Contate um administrador.", discord.Color.red())  
        await interaction.response.send_message(embed=embed, ephemeral=True)  
        return  

    # Salva participantes e canais  
    self.participants.add(user.id)  
    self.user_channels[user.id] = texto.id  
    self.user_voice_channels[user.id] = voz.id  

    # Embed de boas-vindas na sala privada  
    embed_sala = embed_base(  
        "🎮 Sala Criada com Sucesso",  
        f"Olá {user.mention}, sua sala está pronta!",  
        discord.Color.green()  
    )  
    embed_sala.add_field(name="👤 Jogador", value=user.display_name, inline=True)  
    embed_sala.add_field(name="⚔️ Modo", value=self.modo, inline=True)  
    embed_sala.add_field(name="💰 Prêmio", value=f"🪙 {self.premio} 🪙", inline=True)  
    embed_sala.add_field(name="📋 Instruções", value="Aguardue o adversário ou utilize o botão abaixo para fechar a sala.", inline=False)  
    embed_sala.set_thumbnail(url=config.get("logo") or None)  

    # Botão para fechar a sala dentro do canal privado  
    view_fechar = View(timeout=None)  
    fechar_btn = Button(label="Fechar Sala", style=discord.ButtonStyle.red, custom_id=f"fechar_{user.id}")  
    async def fechar_callback(interaction: discord.Interaction):  
        # Apenas o dono da sala ou admin pode fechar  
        if interaction.user.id != user.id and not interaction.user.guild_permissions.administrator:  
            return await interaction.response.send_message("Apenas o dono da sala pode fechá-la.", ephemeral=True)  
        await texto.delete()  
        await voz.delete()  
        # Remove dos registros  
        self.participants.discard(user.id)  
        self.user_channels.pop(user.id, None)  
        self.user_voice_channels.pop(user.id, None)  
        await enviar_log(self.guild, f"🔒 Sala de {user.mention} foi fechada por {interaction.user.mention}", discord.Color.orange())  
    fechar_btn.callback = fechar_callback  
    view_fechar.add_item(fechar_btn)  
    await texto.send(embed=embed_sala, view=view_fechar)  

    # Log  
    await enviar_log(self.guild, f"🆕 {user.mention} entrou na partida. Canal: {texto.mention}", discord.Color.green())  

    # Confirmação para o usuário  
    confirm = embed_base("✅ Entrada Confirmada", f"Sua sala foi criada: {texto.mention}\nCanal de voz: {voz.mention}", discord.Color.green())  
    await interaction.response.send_message(embed=confirm, ephemeral=True)  

# -----------------------------------------------  
# BOTÃO 🔴 SAIR  
# -----------------------------------------------  
@discord.ui.button(label="Sair", style=discord.ButtonStyle.red, custom_id="apostado_sair")  
async def sair(self, interaction: discord.Interaction, button: Button):  
    user = interaction.user  
    if user.id not in self.participants:  
        embed = embed_base("❌ Erro", "Você não está na partida.", discord.Color.red())  
        await interaction.response.send_message(embed=embed, ephemeral=True)  
        return  

    # Remove canais  
    texto_id = self.user_channels.pop(user.id, None)  
    voz_id = self.user_voice_channels.pop(user.id, None)  
    self.participants.discard(user.id)  

    for cid in [texto_id, voz_id]:  
        if cid:  
            canal = self.guild.get_channel(cid)  
            if canal:  
                try:  
                    await canal.delete()  
                except discord.Forbidden:  
                    pass  

    await enviar_log(self.guild, f"🚪 {user.mention} saiu da partida.", discord.Color.orange())  
    embed = embed_base("👋 Saída", "Você foi removido da partida com sucesso.", discord.Color.green())  
    await interaction.response.send_message(embed=embed, ephemeral=True)  

# -----------------------------------------------  
# BOTÃO ⚙️ INFO  
# -----------------------------------------------  
@discord.ui.button(label="Info", style=discord.ButtonStyle.blurple, custom_id="apostado_info")  
async def info(self, interaction: discord.Interaction, button: Button):  
    jogadores = ", ".join([f"<@{uid}>" for uid in self.participants]) if self.participants else "Nenhum"  
    embed = embed_base("ℹ️ Informações da Partida", "", discord.Color.blue())  
    embed.add_field(name="⚔️ Modo", value=self.modo, inline=True)  
    embed.add_field(name="🎟️ Valor de entrada", value=self.valor, inline=True)  
    embed.add_field(name="🏆 Prêmio", value=f"🪙 {self.premio} 🪙", inline=True)  
    embed.add_field(name="👥 Jogadores atuais", value=jogadores, inline=False)  
    embed.set_thumbnail(url=config.get("logo") or None)  
    await interaction.response.send_message(embed=embed, ephemeral=True)

#============================================================

#COMANDOS DO BOT

#============================================================

#----------------------------------------------------------

#COMANDO !apostado

#----------------------------------------------------------
@bot.command(name="apostado")
@commands.has_permissions(administrator=True)
async def apostado(ctx, modo: str = "X1", valor: str = "R$10", premio: str = "R$100"):
    """
    Envia o embed principal da partida com botões interativos.
    Uso: !apostado [modo] [valor] [prêmio]
    """

    # Verifica canal específico
    if config["canal_apostado"] and str(ctx.channel.id) != config["canal_apostado"]:
        embed = embed_base(
            "❌ Canal incorreto",
            f"Use este comando em <#{config['canal_apostado']}>",
            discord.Color.red()
        )
        return await ctx.send(embed=embed, delete_after=5)

    embed = discord.Embed(
        title="🔥 APOSTADO DISPONÍVEL",
        description=f"**Modo:** {modo}\n**Valor de entrada:** {valor}\n**Status:** Aguardando jogadores",
        color=0xFFD700
    )

    # Campo de prêmio em destaque
    embed.add_field(
        name="🏆 PRÊMIO",
        value=f"✨🪙 **{premio}** 🪙✨",
        inline=False
    )

    # Thumbnail e banner configuráveis
    if config["logo"]:
        embed.set_thumbnail(url=config["logo"])

    if config["banner"]:
        embed.set_image(url=config["banner"])

    embed.set_footer(
        text=f"{ctx.guild.name} • Sistema de Apostados",
        icon_url=ctx.guild.icon.url if ctx.guild.icon else None
    )

    view = ApostadoView(modo, valor, premio, ctx.guild)
    mensagem = await ctx.send(embed=embed, view=view)
    active_views[(ctx.guild.id, mensagem.id)] = view

#----------------------------------------------------------

#COMANDO !pagamento

#----------------------------------------------------------

@bot.command(name="pagamento")
@commands.has_permissions(administrator=True)
async def pagamento(ctx):
"""Envia o embed com QR Code e instruções de pagamento."""
if not config["qr_code"]:
embed = embed_base("❌ QR Code não configurado", "Use !setqr <url> para definir a imagem do QR Code.", discord.Color.red())
return await ctx.send(embed=embed)

embed = discord.Embed(  
    title="💰 PAGAMENTO",  
    description="Escaneie o QR Code abaixo para realizar o pagamento.",  
    color=discord.Color.gold()  
)  
embed.set_image(url=config["qr_code"])  
embed.add_field(name="📌 Instruções", value="Após o pagamento, envie o comprovante para um administrador.", inline=False)  
embed.set_footer(text="Obrigado por jogar conosco!")  
await ctx.send(embed=embed)

# ----------------------------------------------------------
# COMANDO !pagamento
# ----------------------------------------------------------

@bot.command(name="pagamento")
@commands.has_permissions(administrator=True)
async def pagamento(ctx):
    """Envia o embed com QR Code e instruções de pagamento."""
    if not config["qr_code"]:
        embed = embed_base(
            "❌ QR Code não configurado",
            "Use !setqr <url> para definir a imagem do QR Code.",
            discord.Color.red()
        )
        return await ctx.send(embed=embed)

    embed = discord.Embed(
        title="💰 PAGAMENTO",
        description="Escaneie o QR Code abaixo para realizar o pagamento.",
        color=discord.Color.gold()
    )
    embed.set_image(url=config["qr_code"])
    embed.add_field(
        name="📌 Instruções",
        value="Após o pagamento, envie o comprovante para um administrador.",
        inline=False
    )
    embed.set_footer(text="Obrigado por jogar conosco!")
    await ctx.send(embed=embed)


# ----------------------------------------------------------
# COMANDOS DE CONFIGURAÇÃO
# ----------------------------------------------------------

@bot.command(name="setlogo")
@commands.has_permissions(administrator=True)
async def setlogo(ctx, url: str):
    config["logo"] = url
    await ctx.send(embed=embed_base("✅ Logo atualizada", f"Thumbnail definida: {url}", discord.Color.green()))


@bot.command(name="setbanner")
@commands.has_permissions(administrator=True)
async def setbanner(ctx, url: str):
    config["banner"] = url
    await ctx.send(embed=embed_base("✅ Banner atualizado", f"Imagem principal definida: {url}", discord.Color.green()))


@bot.command(name="setcanal")
@commands.has_permissions(administrator=True)
async def setcanal(ctx, canal: discord.TextChannel):
    config["canal_apostado"] = str(canal.id)
    await ctx.send(embed=embed_base("✅ Canal definido", f"Comando !apostado liberado apenas em {canal.mention}", discord.Color.green()))


@bot.command(name="setcategoria")
@commands.has_permissions(administrator=True)
async def setcategoria(ctx, *, nome: str):
    config["categoria_salas"] = nome
    await ctx.send(embed=embed_base("✅ Categoria definida", f"As salas serão criadas na categoria {nome}", discord.Color.green()))


@bot.command(name="setlogs")
@commands.has_permissions(administrator=True)
async def setlogs(ctx, canal: discord.TextChannel):
    config["canal_logs"] = str(canal.id)
    await ctx.send(embed=embed_base("✅ Canal de logs", f"Logs serão enviados para {canal.mention}", discord.Color.green()))


@bot.command(name="setqr")
@commands.has_permissions(administrator=True)
async def setqr(ctx, url: str):
    config["qr_code"] = url
    await ctx.send(embed=embed_base("✅ QR Code definido", "Imagem do pagamento configurada.", discord.Color.green()))


@bot.command(name="configurar")
@commands.has_permissions(administrator=True)
async def configurar(ctx):
    """Exibe todas as configurações atuais."""
    embed = discord.Embed(title="⚙️ Configurações atuais", color=discord.Color.gold())
    embed.add_field(name="Logo", value=config["logo"] or "Não definida", inline=False)
    embed.add_field(name="Banner", value=config["banner"] or "Não definido", inline=False)
    embed.add_field(name="Canal Apostado", value=f"<#{config['canal_apostado']}>" if config["canal_apostado"] else "Todos", inline=True)
    embed.add_field(name="Categoria Salas", value=config["categoria_salas"] or "Nenhuma (raiz)", inline=True)
    embed.add_field(name="Canal Logs", value=f"<#{config['canal_logs']}>" if config["canal_logs"] else "Nenhum", inline=True)
    # ----------------------------------------------------------
# COMANDO !pagamento
# ----------------------------------------------------------

@bot.command(name="pagamento")
@commands.has_permissions(administrator=True)
async def pagamento(ctx):
    """Envia o embed com QR Code e instruções de pagamento."""

    if not config["qr_code"]:
        embed = embed_base(
            "❌ QR Code não configurado",
            "Use !setqr <url> para definir a imagem do QR Code.",
            discord.Color.red()
        )
        return await ctx.send(embed=embed)

    embed = discord.Embed(
        title="💰 PAGAMENTO",
        description="Escaneie o QR Code abaixo para realizar o pagamento.",
        color=discord.Color.gold()
    )

    embed.set_image(url=config["qr_code"])
    embed.add_field(
        name="📌 Instruções",
        value="Após o pagamento, envie o comprovante para um administrador.",
        inline=False
    )

    embed.set_footer(text="Obrigado por jogar conosco!")
    await ctx.send(embed=embed)


# ----------------------------------------------------------
# COMANDOS DE CONFIGURAÇÃO
# ----------------------------------------------------------

@bot.command(name="setlogo")
@commands.has_permissions(administrator=True)
async def setlogo(ctx, url: str):
    config["logo"] = url
    await ctx.send(embed=embed_base("✅ Logo atualizada", f"Thumbnail definida: {url}", discord.Color.green()))


@bot.command(name="setbanner")
@commands.has_permissions(administrator=True)
async def setbanner(ctx, url: str):
    config["banner"] = url
    await ctx.send(embed=embed_base("✅ Banner atualizado", f"Imagem principal definida: {url}", discord.Color.green()))


@bot.command(name="setcanal")
@commands.has_permissions(administrator=True)
async def setcanal(ctx, canal: discord.TextChannel):
    config["canal_apostado"] = str(canal.id)
    await ctx.send(embed=embed_base("✅ Canal definido", f"Comando !apostado liberado apenas em {canal.mention}", discord.Color.green()))


@bot.command(name="setcategoria")
@commands.has_permissions(administrator=True)
async def setcategoria(ctx, *, nome: str):
    config["categoria_salas"] = nome
    await ctx.send(embed=embed_base("✅ Categoria definida", f"As salas serão criadas na categoria {nome}", discord.Color.green()))


@bot.command(name="setlogs")
@commands.has_permissions(administrator=True)
async def setlogs(ctx, canal: discord.TextChannel):
    config["canal_logs"] = str(canal.id)
    await ctx.send(embed=embed_base("✅ Canal de logs", f"Logs serão enviados para {canal.mention}", discord.Color.green()))


@bot.command(name="setqr")
@commands.has_permissions(administrator=True)
async def setqr(ctx, url: str):
    config["qr_code"] = url
    await ctx.send(embed=embed_base("✅ QR Code definido", "Imagem do pagamento configurada.", discord.Color.green()))


@bot.command(name="configurar")
@commands.has_permissions(administrator=True)
async def configurar(ctx):
    """Exibe todas as configurações atuais."""

    embed = discord.Embed(title="⚙️ Configurações atuais", color=discord.Color.gold())

    embed.add_field(name="Logo", value=config["logo"] or "Não definida", inline=False)
    embed.add_field(name="Banner", value=config["banner"] or "Não definido", inline=False)
    embed.add_field(name="Canal Apostado", value=f"<#{config['canal_apostado']}>" if config["canal_apostado"] else "Todos", inline=True)
    embed.add_field(name="Categoria Salas", value=config["categoria_salas"] or "Nenhuma (raiz)", inline=True)
    embed.add_field(name="Canal Logs", value=f"<#{config['canal_logs']}>" if config["canal_logs"] else "Nenhum", inline=True)
    embed.add_field(name="QR Code", value="Configurado" if config["qr_code"] else "Não configurado", inline=True)
    embed.add_field(name="Anti-Spam", value=f"<#{config['canal_antispam']}>" if config["canal_antispam"] else "Desativado", inline=True)

    await ctx.send(embed=embed)


# ----------------------------------------------------------
# COMANDO ANTI-SPAM
# ----------------------------------------------------------

@bot.command(name="setantispam")
@commands.has_permissions(administrator=True)
async def setantispam(ctx, canal: discord.TextChannel):
    config["canal_antispam"] = str(canal.id)
    await ctx.send(embed=embed_base("🛡️ Anti-Spam ativado", f"Mensagens repetidas serão filtradas em {canal.mention}", discord.Color.yellow()))


# ============================================================
# EVENTO ON_MESSAGE (ANTI-SPAM)
# ============================================================

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if config["canal_antispam"] and str(message.channel.id) == config["canal_antispam"]:
        if message.author.guild_permissions.administrator:
            await bot.process_commands(message)
            return

        chave = (message.guild.id, message.author.id, message.channel.id)
        historico = spam_tracker.setdefault(chave, [])

        historico.append(message.content)
        if len(historico) > 3:
            historico.pop(0)

        if len(historico) == 3 and historico[0] == historico[1] == historico[2]:
            try:
                await message.delete()
            except:
                pass

            embed = embed_base(
                "⚠️ Aviso de Spam",
                f"{message.author.mention}, você enviou a mesma mensagem 3 vezes seguidas.",
                discord.Color.orange()
            )

            aviso = await message.channel.send(embed=embed)
            await asyncio.sleep(5)

            try:
                await aviso.delete()
            except:
                pass

            historico.clear()

            await enviar_log(
                message.guild,
                f"🚫 Spam detectado de {message.author.mention}",
                discord.Color.red()
            )

    await bot.process_commands(message)


# ============================================================
# EVENTO ON_READY
# ============================================================

@bot.event
async def on_ready():
    print(f"✅ Bot online como {bot.user}")

# ============================================================
# EXECUÇÃO SEGURA
# ============================================================

TOKEN = os.getenv("TOKEN")
if TOKEN is None:
    raise ValueError("A variável de ambiente 'TOKEN' não foi definida.")

bot.run(TOKEN)
