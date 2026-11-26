from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from database.mysql_connection import connection_mysql
from auth.router import get_current_user
from datetime import date, timedelta 
from routers.helpers_router import  (
    _empresas_permitidas,
    _aplicar_filtro_empresa,
    _in,
    _nomes_pessoas
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# GET /dre  
# ─────────────────────────────────────────────────────────────
@router.get("/dre")
def get_dre(
    id_empresa: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    incluir_abertos: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    conn = connection_mysql()
    cursor = conn.cursor(dictionary=True)

    try:
        filtros = ["tenant_id = %s"]
        params = [current_user["tenant_id"]]

        permitidas = _empresas_permitidas(current_user)
        _aplicar_filtro_empresa(filtros, params, id_empresa, permitidas)

        if data_inicio:
            inicio = date.fromisoformat(data_inicio).replace(day=1)
            filtros.append("mes_competencia >= %s")
            params.append(inicio.isoformat())

        if data_fim:
            filtros.append("mes_competencia <= %s")
            params.append(data_fim)

        if not incluir_abertos:
            filtros.append("em_aberto = 0")

        where = f"WHERE {' AND '.join(filtros)}"

        sql = f"""
            SELECT
                pc.classificacao,
                pc.descricao,
                pc.eh_analitica,
                v.id_empresa,
                v.id_pessoa,
                SUM(v.valor_dre) AS total,
                MAX(v.ultima_atualizacao) AS ultima_atualizacao
            FROM dim_plano_contas pc
            JOIN (
                SELECT
                    numero_conta_resultado,
                    id_empresa,
                    id_pessoa,
                    SUM(valor_dre) AS valor_dre,
                    MAX(ultima_atualizacao) AS ultima_atualizacao
                FROM vw_bi_dre
                {where}
                GROUP BY numero_conta_resultado, id_empresa, id_pessoa
            ) v
                ON v.numero_conta_resultado = pc.classificacao
                OR v.numero_conta_resultado LIKE CONCAT(pc.classificacao, '.%%')
            WHERE pc.grupo = 'Resultado'
            GROUP BY pc.classificacao, pc.descricao, pc.eh_analitica, v.id_empresa, v.id_pessoa
            HAVING pc.eh_analitica = 0 OR total <> 0
            ORDER BY pc.classificacao
        """

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        nomes = _nomes_pessoas(cursor, {r["id_pessoa"] for r in rows})

        for row in rows:
            row["total"] = float(row["total"])
            row["eh_analitica"] = bool(row["eh_analitica"])
            row["nome_pessoa"] = nomes.get(str(row["id_pessoa"]))
            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()

        return {"total": len(rows), "data": rows}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

_CANDIDATOS = {
    "descricao": ["descricao", "descricao_titulo", "historico", "observacao"],
}

_COLS_NOME_EMPRESA = ["nome_fantasia", "razao_social", "nome_empresa", "nome", "fantasia", "descricao"]


def _in(n: int) -> str:
    return ",".join(["%s"] * n)


@router.get("/dre/titulos")
def get_dre_titulos(
    classificacao: str = Query(...),
    id_empresa: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    conn = connection_mysql()
    cursor = conn.cursor(dictionary=True)

    try:
        filtros = [
            "f.tenant_id = %s",
            "f.tipo_titulo IN ('RECEBER','PAGAR')",
            "UPPER(f.descricao_situacao) NOT IN ('CANCELADO', 'UNIDO', 'RENEGOCIADO')",
            "f.numero_conta_resultado = %s",
        ]
        params = [current_user["tenant_id"], classificacao]

        permitidas = _empresas_permitidas(current_user)
        _aplicar_filtro_empresa(filtros, params, id_empresa, permitidas)

        if data_inicio:
            ini = date.fromisoformat(data_inicio).replace(day=1)
            filtros.append("f.data_competencia >= %s")
            params.append(ini.isoformat())
        if data_fim:
            fim = date.fromisoformat(data_fim)
            prox_mes = (fim.replace(day=1) + timedelta(days=32)).replace(day=1)
            filtros.append("f.data_competencia <= %s")
            params.append(prox_mes.isoformat())

        sql = f"""
            SELECT
                f.*,
                COALESCE((
                    SELECT r.valor_pago
                    FROM vw_bi_financeiro_recebimento r
                    WHERE CAST(r.codigo_titulo AS CHAR) = CAST(f.codigo_titulo AS CHAR)
                    ORDER BY r.data_movimentacao DESC
                    LIMIT 1
                ), 0) AS valor_pago_calc
            FROM vw_bi_financeiro_titulo f
            WHERE {' AND '.join(filtros)}
            ORDER BY f.data_competencia, f.codigo_titulo
        """

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        # ── Nomes: busca só os IDs presentes nos títulos (evita varrer as tabelas inteiras)
        ids_empresa = sorted({str(r["id_empresa"]) for r in rows if r.get("id_empresa") not in (None, "")})
        ids_pessoa = sorted({str(r["id_pessoa"]) for r in rows if r.get("id_pessoa") not in (None, "")})

        nomes_empresa: dict = {}
        if ids_empresa:
            cursor.execute(
                f"SELECT * FROM dim_empresa WHERE codigo_empresa IN ({_in(len(ids_empresa))})",
                ids_empresa,
            )
            for e in cursor.fetchall():
                nome = next((e[c] for c in _COLS_NOME_EMPRESA if e.get(c)), None)
                nomes_empresa.setdefault(str(e["codigo_empresa"]), nome)

        nomes_pessoa: dict = {}
        if ids_pessoa:
            cursor.execute(
                f"""SELECT codigo_sances, MAX(nome) AS nome
                    FROM dim_pessoa
                    WHERE codigo_sances IN ({_in(len(ids_pessoa))})
                    GROUP BY codigo_sances""",
                ids_pessoa,
            )
            for p in cursor.fetchall():
                nomes_pessoa[str(p["codigo_sances"])] = p["nome"]

        for row in rows:
            bruto = float(row.get("valor_total") or 0)
            nominal = float(row.get("valor_nominal") or bruto)
            pago = float(row.pop("valor_pago_calc") or 0)
            tipo = row.get("tipo_titulo")
            sinal = 1 if tipo == "RECEBER" else -1 if tipo == "PAGAR" else 0
            parcial = (row.get("descricao_situacao") or "").upper() == "BAIXADO PARCIAL"
            saldo = max(nominal - pago, 0.0) if parcial else bruto
            row["valor_total"] = sinal * saldo
            row["valor_pago"] = pago

            row["codigo"] = row.get("codigo_titulo")
            row["nome_empresa"] = nomes_empresa.get(str(row.get("id_empresa")))
            row["nome_pessoa"] = nomes_pessoa.get(str(row.get("id_pessoa")))

            for alvo, nomes in _CANDIDATOS.items():
                if row.get(alvo) is None:
                    row[alvo] = next((row[n] for n in nomes if row.get(n) is not None), None)
            if not row.get("descricao"):
                row["descricao"] = row.get("descricao_conta_resultado")
            if not row.get("origem"):
                row["origem"] = tipo

            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()

        rows = [r for r in rows if r["valor_total"] != 0]
        return {"total": len(rows), "data": rows}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

_DRE_CLASSE_DESPESAS = "3.3"
 
 
@router.get("/despesas-mensal")
def get_dre_despesas_mensal(
    id_empresa: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    incluir_abertos: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    """Contas analíticas de despesa × empresa × mês (alimenta os gráficos de linha da DRE)."""
    conn = connection_mysql()
    cursor = conn.cursor(dictionary=True)
 
    try:
        filtros = [
            "tenant_id = %s",
            "(numero_conta_resultado = %s OR numero_conta_resultado LIKE %s)",
        ]
        params = [current_user["tenant_id"], _DRE_CLASSE_DESPESAS, f"{_DRE_CLASSE_DESPESAS}.%"]
 
        permitidas = _empresas_permitidas(current_user)
        _aplicar_filtro_empresa(filtros, params, id_empresa, permitidas)
 
        if data_inicio:
            inicio = date.fromisoformat(data_inicio).replace(day=1)
            filtros.append("mes_competencia >= %s")
            params.append(inicio.isoformat())
        if data_fim:
            filtros.append("mes_competencia <= %s")
            params.append(data_fim)
        if not incluir_abertos:
            filtros.append("em_aberto = 0")
 
        sql = f"""
            SELECT
                pc.classificacao,
                pc.descricao,
                v.id_empresa,
                v.id_pessoa,
                v.periodo,
                v.total
            FROM dim_plano_contas pc
            JOIN (
                SELECT id_empresa,
                       id_pessoa,
                       numero_conta_resultado,
                       LEFT(mes_competencia, 7) AS periodo,
                       SUM(valor_dre)           AS total
                FROM vw_bi_dre
                WHERE {' AND '.join(filtros)}
                GROUP BY id_empresa, id_pessoa, numero_conta_resultado, LEFT(mes_competencia, 7)
            ) v ON v.numero_conta_resultado = pc.classificacao
            WHERE pc.grupo = 'Resultado' AND pc.eh_analitica = 1
            ORDER BY pc.classificacao, v.periodo
        """
 
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        nomes = _nomes_pessoas(cursor, {r["id_pessoa"] for r in rows})
        for row in rows:
            row["total"] = float(row["total"] or 0)
            row["nome_pessoa"] = nomes.get(str(row["id_pessoa"]))
 
        return {"total": len(rows), "data": rows}
 
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()