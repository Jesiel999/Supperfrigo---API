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
# GET /fcp  — retorna conta × empresa × mês (periodo "YYYY-MM")
# ─────────────────────────────────────────────────────────────
@router.get("/fcp")
def get_fcp(
    id_empresa: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
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
            ini = f"{data_inicio}-01" if len(data_inicio) == 7 else data_inicio
            filtros.append("mes_competencia >= %s")
            params.append(ini)

        if data_fim:
            if len(data_fim) == 7:
                ano, mes = map(int, data_fim.split("-"))
                prox_mes = date(ano + (mes // 12), (mes % 12) + 1, 1)
                fim = (prox_mes - timedelta(days=1)).isoformat()
            else:
                fim = data_fim
            filtros.append("mes_competencia <= %s")
            params.append(fim)

        where = f"WHERE {' AND '.join(filtros)}"

        sql = f"""
            SELECT
                pc.classificacao,
                pc.descricao,
                pc.eh_analitica,
                v.id_empresa,
                v.id_pessoa,
                v.periodo,
                SUM(v.valor_dre) AS total,
                MAX(v.ultima_atualizacao) AS ultima_atualizacao
            FROM dim_plano_contas pc
            JOIN (
                SELECT id_empresa,
                       id_pessoa,
                       numero_conta_resultado,
                       LEFT(mes_competencia, 7) AS periodo,
                       SUM(valor_dre)           AS valor_dre,
                       MAX(ultima_atualizacao)  AS ultima_atualizacao
                FROM vw_bi_fcp
                {where}
                GROUP BY id_empresa, id_pessoa, numero_conta_resultado, LEFT(mes_competencia, 7)
            ) v
              ON v.numero_conta_resultado = pc.classificacao
              OR v.numero_conta_resultado LIKE CONCAT(pc.classificacao, '.%%')
            WHERE pc.grupo = 'Resultado'
            GROUP BY pc.classificacao, pc.descricao, pc.eh_analitica, v.id_empresa, v.id_pessoa, v.periodo
            ORDER BY pc.classificacao, v.periodo
        """

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        nomes = _nomes_pessoas(cursor, {r["id_pessoa"] for r in rows})

        for row in rows:
            row["total"] = float(row["total"] or 0)
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

# Contas de resultado consideradas "a pagar": custos (3.2) e despesas (3.3).
_FCP_CLASSES_PAGAR = ("3.2", "3.3")

# Nome da empresa em dim_empresa
_FCP_COLS_NOME_EMPRESA = ["nome_fantasia", "razao_social", "nome_empresa", "nome", "fantasia", "descricao"]


def _fcp_in(n: int) -> str:
    return ",".join(["%s"] * n)


@router.get("/fcp/pagar")
def get_fcp_pagar(
    id_empresa: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    base_data: str = Query("competencia", pattern="^(competencia|vencimento)$"),
    current_user: dict = Depends(get_current_user),
):
    """Títulos a PAGAR EM ABERTO de custos e despesas, com fornecedor, nota, parcela e valores.
    base_data: 'competencia' (padrão, mesma base do resto do FCP) ou 'vencimento'.
    """
    conn = connection_mysql()
    cursor = conn.cursor(dictionary=True)

    try:
        filtros = [
            "f.tenant_id = %s",
            "f.tipo_titulo = 'PAGAR'",
            "UPPER(f.descricao_situacao) NOT IN ('CANCELADO', 'BAIXADO', 'BAIXADO PARCIAL', 'UNIDO', 'RENEGOCIADO')",
        ]
        params = [current_user["tenant_id"]]

        conds = " OR ".join(
            ["(f.numero_conta_resultado = %s OR f.numero_conta_resultado LIKE %s)"] * len(_FCP_CLASSES_PAGAR)
        )
        filtros.append(f"({conds})")
        for c in _FCP_CLASSES_PAGAR:
            params += [c, f"{c}.%"]

        permitidas = _empresas_permitidas(current_user)
        _aplicar_filtro_empresa(filtros, params, id_empresa, permitidas)

        col_data = "f.data_competencia" if base_data == "competencia" else "f.data_vencimento"
        if data_inicio:
            ini = date.fromisoformat(data_inicio)
            filtros.append(f"{col_data} >= %s")
            params.append(ini.isoformat())

        if data_fim:
            fim = date.fromisoformat(data_fim)
            filtros.append(f"{col_data} <= %s")
            params.append(fim.isoformat())

        sql = f"""
            SELECT
                f.codigo_titulo                   AS codigo,
                f.id_empresa,
                f.id_pessoa,
                f.numero_documento,
                f.ordem                           AS parcela,
                f.origem,
                f.descricao_situacao,
                f.status_financeiro,
                f.descricao_forma_pagamento,
                f.descricao_categoria_financeira,
                f.descricao_centro_custo,
                f.numero_conta_resultado,
                f.descricao_conta_resultado,
                f.data_emissao,
                f.data_competencia,
                f.data_vencimento,
                f.data_baixa,
                f.dias_atraso,
                f.valor_nominal                   AS valor_titulo,
                f.valor_total                     AS valor_total_bruto,
                COALESCE((
                    SELECT SUM(r.valor_pago)
                    FROM vw_bi_financeiro_recebimento r
                    WHERE r.codigo_titulo = f.codigo_titulo
                ), 0)                             AS valor_pago,
                CASE
                    WHEN f.numero_documento IS NULL OR f.numero_documento = '' THEN f.valor_nominal
                    ELSE (
                        SELECT SUM(x.valor_nominal)
                        FROM vw_bi_financeiro_titulo x
                        WHERE x.tenant_id        = f.tenant_id
                          AND x.id_empresa       = f.id_empresa
                          AND x.id_pessoa        = f.id_pessoa
                          AND x.numero_documento = f.numero_documento
                          AND x.tipo_titulo      = 'PAGAR'
                          AND UPPER(x.descricao_situacao) NOT IN ('CANCELADO', 'BAIXADO', 'BAIXADO PARCIAL', 'UNIDO', 'RENEGOCIADO')
                    )
                END                               AS valor_nota
            FROM vw_bi_financeiro_titulo f
            WHERE {' AND '.join(filtros)}
        """

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        ids_empresa = sorted({str(r["id_empresa"]) for r in rows if r.get("id_empresa") not in (None, "")})
        ids_pessoa = sorted({str(r["id_pessoa"]) for r in rows if r.get("id_pessoa") not in (None, "")})

        nomes_empresa: dict = {}
        if ids_empresa:
            cursor.execute(
                f"SELECT * FROM dim_empresa WHERE codigo_empresa IN ({_fcp_in(len(ids_empresa))})",
                ids_empresa,
            )
            for e in cursor.fetchall():
                nome = next((e[c] for c in _FCP_COLS_NOME_EMPRESA if e.get(c)), None)
                nomes_empresa.setdefault(str(e["codigo_empresa"]), nome)

        nomes_pessoa: dict = {}
        if ids_pessoa:
            cursor.execute(
                f"""SELECT codigo_sances, MAX(nome) AS nome
                    FROM dim_pessoa
                    WHERE codigo_sances IN ({_fcp_in(len(ids_pessoa))})
                    GROUP BY codigo_sances""",
                ids_pessoa,
            )
            for p in cursor.fetchall():
                nomes_pessoa[str(p["codigo_sances"])] = p["nome"]

        for row in rows:
            nominal = float(row.get("valor_titulo") or 0)
            pago = float(row.get("valor_pago") or 0)
            situacao = (row.get("descricao_situacao") or "").upper()

            row["valor_titulo"] = nominal
            row["valor_pago"] = pago
            row["valor_nota"] = float(row.get("valor_nota") or nominal)
            bruto = float(row.pop("valor_total_bruto") or nominal)
            row["valor_em_aberto"] = max(nominal - pago, 0.0) if situacao == "BAIXADO PARCIAL" else bruto

            row["nome_empresa"] = nomes_empresa.get(str(row.get("id_empresa")))
            row["nome_fornecedor"] = nomes_pessoa.get(str(row.get("id_pessoa")))

            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()

        rows = [r for r in rows if r["valor_em_aberto"] > 0]

        rows.sort(key=lambda r: (
            (r.get("nome_fornecedor") or "~").lower(),
            str(r.get("numero_documento") or ""),
            str(r.get("parcela") or ""),
            str(r.get("data_vencimento") or ""),
        ))

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

@router.get("/fcp/titulos")
def get_fcp_titulos(
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
            "UPPER(f.descricao_situacao) NOT IN ('CANCELADO', 'UNIDO', 'RENEGOCIADO', 'BAIXADO', 'BAIXADO PARCIAL')",
            "f.numero_conta_resultado = %s",
        ]
        params = [current_user["tenant_id"], classificacao]

        permitidas = _empresas_permitidas(current_user)
        _aplicar_filtro_empresa(filtros, params, id_empresa, permitidas)

        if data_inicio:
            filtros.append("f.data_competencia >= %s")
            params.append(data_inicio)
        if data_fim:
            filtros.append("f.data_competencia <= %s")
            params.append(data_fim)

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
