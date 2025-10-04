import asyncio
import aiohttp
import os
import json
from collections import defaultdict, deque
from datetime import datetime
from bot.utils import send_telegram_message
from config import ROULETTES

ORPHELINS = [1, 20, 14, 31, 9, 6, 34, 17]

MINIMO_OCORRENCIAS = 5
MINIMO_RODADAS_ANALISE = 50
HISTORICO_COMPLETO_SIZE = 500
TENDENCIA_UPDATE_INTERVAL = 10

API_URL = "https://casino.dougurasu-bets.online:9000/playtech/results.json"
LINK_MESA_BASE = "https://geralbet.bet.br/live-casino/game/3763038"
# MONITORING_FILE = "/var/www/html/autobot/orph_bot.json"
MONITORING_FILE = "orph_bot.json"


estado_mesas = defaultdict(
    lambda: {
        "status": "idle",
        "entrada": None,
        "gale": 0,
        "monitorando": False,
        "greens": 0,
        "greens_g1": 0,
        "greens_g2": 0,
        "loss": 0,
        "total": 0,
        "consec_greens": 0,
        "ultimo_resultado_validado": None,
        "data_atual": datetime.now().date(),
        "historico": deque(maxlen=HISTORICO_COMPLETO_SIZE),
        "sinais_enviados": 0,
        "aguardando_confirmacao": False,
        "tendencias": {},
        "top_tendencias": [],
        "contador_rodadas": 0,
        "ultima_atualizacao_tendencias": None,
        "entrada_ativa": False,
        "numero_entrada": None,
        "gale": 0,
        "greens_consecutivos": 0,
        "entrada_real": False,
        "entradas": 0,
        "aguardando_novo_numero": False,
        "ultimos_5_processados": [],
    }
)


def pertence_ao_padrao(numero):
    return numero in ORPHELINS


def analisar_tendencias(historico):
    historico = list(historico)
    tendencias = {n: {"chamou_orph": 0, "total": 0} for n in ORPHELINS}

    for idx in range(3, len(historico)):
        numero_atual = historico[idx]
        anteriores = historico[idx - 3 : idx][::-1]

        if numero_atual in ORPHELINS:
            for anterior in anteriores:
                if pertence_ao_padrao(anterior):
                    tendencias[numero_atual]["chamou_orph"] += 1
                    break

            tendencias[numero_atual]["total"] += 1

    for numero in tendencias:
        total = tendencias[numero]["total"]
        chamou_orph = tendencias[numero]["chamou_orph"]
        porcentagem = round((chamou_orph / total * 100), 2) if total > 0 else 0
        tendencias[numero]["porcentagem"] = porcentagem

    return tendencias


def get_numeros_validos(tendencias):
    """Retorna números órfãos que tiveram pelo menos 5 ocorrências de 'órfão pagou órfão'"""
    numeros_validos = []
    for numero, stats in tendencias.items():
        if stats["total"] >= 5:  # Mínimo 5 ocorrências
            numeros_validos.append(numero)
    return numeros_validos


async def notificar_entrada(roulette_id, numero, tendencias):
    stats = tendencias[numero]
    message = (
        f"🔥 ENTRADA ORPHELINS - {numero} ({stats['chamou_orph']}/{stats['total']})\n"
    )
    await send_telegram_message(message, LINK_MESA_BASE)


async def fetch_results_http(session, mesa_nome):
    try:
        async with session.get(
            API_URL, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                resultados = data.get(mesa_nome, {}).get("results", [])
                return [
                    int(r["number"])
                    for r in resultados
                    if r.get("number", "").isdigit()
                ]
            else:
                print(f"[ERRO] Status HTTP {resp.status} ao buscar resultados")
                return []
    except asyncio.TimeoutError:
        print(f"[ERRO] Timeout ao buscar resultados da API")
        return []
    except Exception as e:
        print(f"[ERRO] Erro ao buscar resultados: {str(e)}")
        return []


def salvar_dados_monitoramento():
    """Salva os dados de monitoramento em tempo real no arquivo JSON"""
    try:
        # Garantir que o diretório existe
        dir_path = os.path.dirname(MONITORING_FILE)
        if dir_path:  # Só cria diretório se não for vazio
            os.makedirs(dir_path, exist_ok=True)

        # Pegar dados da primeira mesa (Roleta Brasileira)
        mesa = list(estado_mesas.values())[0] if estado_mesas else {}

        # Preparar dados essenciais para salvamento
        entradas_feitas = mesa.get("entradas", 0)
        entrada_real = mesa.get("entrada_real", False)
        entradas_restantes = 3 - entradas_feitas if entrada_real else 0

        dados_monitoramento = {
            "horario": datetime.now().strftime("%H:%M:%S"),
            "greens_consecutivos": mesa.get("greens_consecutivos", 0),
            "entrada_real": entrada_real,
            "entradas": entradas_feitas,
            "entradas_restantes": entradas_restantes,
            "top_tendencias": mesa.get("top_tendencias", []),
        }

        # Salvar no arquivo JSON
        with open(MONITORING_FILE, "w", encoding="utf-8") as f:
            json.dump(dados_monitoramento, f, indent=2, ensure_ascii=False)


    except Exception as e:
        print(f"[ERRO] Falha ao salvar dados de monitoramento: {str(e)}")


async def monitor_roulette(roulette_id):
    print(f"[INICIANDO] Monitorando mesa: {roulette_id}")
    mesa = estado_mesas[roulette_id]
    mesa["notificacao_inicial_enviada"] = False
    mesa["ultima_porcentagem_top"] = {}
    mesa["entrada_ativa"] = False
    mesa["numero_entrada"] = None
    mesa["gale"] = 0
    mesa["ultimo_numero_processado"] = None

    salvar_dados_monitoramento()

    # Criar sessão uma única vez para manter conexão ativa
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30),
        connector=aiohttp.TCPConnector(limit=100, limit_per_host=30, ssl=False),
    )

    while True:
        try:
            # Verificar se a sessão ainda está ativa, se não, recriar
            if session.closed:
                session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30),
                    connector=aiohttp.TCPConnector(
                        limit=100, limit_per_host=30, ssl=False
                    ),
                )

            hoje = datetime.now().date()
            if mesa["data_atual"] != hoje:
                mesa.update(
                    {
                        "greens": 0,
                        "greens_g1": 0,
                        "greens_g2": 0,
                        "loss": 0,
                        "total": 0,
                        "consec_greens": 0,
                        "data_atual": hoje,
                        "sinais_enviados": 0,
                        "notificacao_inicial_enviada": False,
                        "ultima_porcentagem_top": {},
                        "contador_rodadas": 0,
                    }
                )

            resultados = await fetch_results_http(session, roulette_id)
            if not resultados:
                await asyncio.sleep(2)
                continue

            mesa["historico"] = deque(
                resultados[:HISTORICO_COMPLETO_SIZE], maxlen=HISTORICO_COMPLETO_SIZE
            )
            historico_size = len(mesa["historico"])
            mesa["contador_rodadas"] += 1

            if historico_size >= MINIMO_RODADAS_ANALISE:
                nova_tendencia = analisar_tendencias(mesa["historico"])
                numeros_validos = get_numeros_validos(nova_tendencia)

                top_tendencias_anterior = set(mesa["top_tendencias"])
                top_tendencias_atual = set(numeros_validos)
                top_tendencias_mudou = top_tendencias_anterior != top_tendencias_atual

                mesa["tendencias"] = nova_tendencia
                mesa["top_tendencias"] = numeros_validos

                if top_tendencias_mudou:
                    print(
                        f"[MONITORING] Lista de números válidos mudou: {top_tendencias_anterior} -> {top_tendencias_atual}"
                    )
                    salvar_dados_monitoramento()

                # Comparar os 5 primeiros elementos da lista para detectar mudanças
                historico_atual = list(mesa["historico"])[:5]
                historico_anterior = mesa.get("ultimos_5_processados", [])

                if historico_atual == historico_anterior:
                    await asyncio.sleep(2)
                    continue

                # Atualizar os últimos 5 processados
                mesa["ultimos_5_processados"] = historico_atual.copy()
                numero_atual = historico_atual[0]

                if not mesa["entrada_ativa"] and numero_atual in numeros_validos:
                    mesa["entrada_ativa"] = True
                    mesa["numero_entrada"] = numero_atual
                    mesa["gale"] = 0

                    if mesa["entrada_real"] and mesa["entradas"] < 3:
                        mesa["entradas"] += 1
                        print(f"[ENTRADA REAL] #{mesa['entradas']}")
                        await notificar_entrada(
                            roulette_id, numero_atual, nova_tendencia
                        )

                elif mesa["entrada_ativa"]:
                    if pertence_ao_padrao(numero_atual):
                        mesa["greens"] += 1
                        mesa["total"] += 1
                        if mesa["gale"] == 1:
                            mesa["greens_g1"] += 1
                        elif mesa["gale"] == 2:
                            mesa["greens_g2"] += 1

                        if mesa["entrada_real"]:
                            mesa["entrada_ativa"] = False
                            mesa["numero_entrada"] = None
                            mesa["gale"] = 0
                            mesa["greens_consecutivos"] += 1
                            await send_telegram_message(
                                f"✅✅✅ GREEN!!! ✅✅✅\n\n({numero_atual}|{mesa['historico'][1]}|{mesa['historico'][2]})"
                            )

                            if mesa["entradas"] == 3:
                                mesa["entrada_real"] = False
                                mesa["entradas"] = 0
                        else:
                            mesa["entrada_ativa"] = False
                            mesa["numero_entrada"] = None
                            mesa["gale"] = 0
                            mesa["greens_consecutivos"] += 1
                            print(
                                f"[GREEN SILENCIOSO] #{mesa['greens_consecutivos']} {numero_atual}"
                            )

                            if mesa["greens_consecutivos"] == 7:
                                mesa["entrada_real"] = True
                                print(f"[ALERTA DE 7 GREENS] - {numero_atual}")
                                msg = f"⚠️ ORPHELINS ⚠️\n\n🚨 7 GREENS CONSECUTIVOS! 🚨\n"
                                await send_telegram_message(msg, LINK_MESA_BASE)

                        salvar_dados_monitoramento()

                    elif mesa["gale"] == 0:
                        mesa["gale"] = 1
                        if mesa["entrada_real"]:
                            await send_telegram_message(
                                f"🔁 Primeiro GALE ({numero_atual})"
                            )
                    elif mesa["gale"] == 1:
                        mesa["gale"] = 2
                        if mesa["entrada_real"]:
                            await send_telegram_message(
                                f"🔁 Segundo e último GALE ({numero_atual})"
                            )
                    else:
                        mesa["loss"] += 1
                        mesa["total"] += 1
                        if mesa["entrada_real"]:
                            await send_telegram_message(
                                f"❌❌❌ LOSS!!! ❌❌❌\n\n({numero_atual}|{mesa['historico'][1]}|{mesa['historico'][2]})"
                            )
                            mesa["entrada_ativa"] = False
                            mesa["numero_entrada"] = None
                            mesa["gale"] = 0
                            mesa["greens_consecutivos"] = 0

                            if mesa["entradas"] == 3:
                                mesa["entrada_real"] = False
                                mesa["entradas"] = 0
                        else:
                            print(f"[LOSS SILENCIOSO] {numero_atual}")
                            mesa["entrada_ativa"] = False
                            mesa["numero_entrada"] = None
                            mesa["gale"] = 0
                            mesa["greens_consecutivos"] = 0

                        salvar_dados_monitoramento()

            await asyncio.sleep(2)

        except Exception as e:
            print(f"[ERRO] {roulette_id}: {str(e)}")
            print(f"[ERRO] Tipo do erro: {type(e).__name__}")
            await asyncio.sleep(5)


async def start_all():
    tasks = [asyncio.create_task(monitor_roulette(mesa)) for mesa in ROULETTES]
    await asyncio.gather(*tasks)


async def main():
    """Função principal com tratamento de erros e reinicialização automática"""
    while True:
        try:
            await start_all()
        except KeyboardInterrupt:
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[ERRO SISTEMA] Erro crítico: {str(e)}")
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[SISTEMA] Bot finalizado pelo usuário")
    except Exception as e:
        print(f"[ERRO CRÍTICO] {str(e)}")
        import sys
        import subprocess

        subprocess.run([sys.executable, __file__])
