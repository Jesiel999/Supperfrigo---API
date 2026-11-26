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
# GET /fluxo de caixa  
# ─────────────────────────────────────────────────────────────
@router.get("/fluxo-caixa")
def get_fluxo_caixa(
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
            inicio = date.fromisoformat(data_inicio).replace(day=1)
            filtros.append("mes_baixa >= %s")
            params.append(inicio.isoformat())

        if data_fim:
            filtros.append("mes_baixa <= %s")
            params.append(data_fim)

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
                       LEFT(mes_baixa, 7) AS periodo,
                       SUM(valor_caixa)         AS valor_dre,
                       MAX(ultima_atualizacao)  AS ultima_atualizacao
                FROM vw_bi_fluxo_caixa
                {where}
                GROUP BY id_empresa, id_pessoa, numero_conta_resultado, LEFT(mes_baixa, 7)
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

# ─────────────────────────────────────────────────────────────
# GET /fluxo de caixa - títulos
# ─────────────────────────────────────────────────────────────
@router.get("/fluxo-caixa/titulos")
def get_fluxo_caixa_titulos(
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
            "UPPER(f.descricao_situacao) IN ('BAIXADO','BAIXADO PARCIAL')",
            "f.data_baixa IS NOT NULL",
            "f.numero_conta_resultado = %s",
        ]
        params = [current_user["tenant_id"], classificacao]

        permitidas = _empresas_permitidas(current_user)
        _aplicar_filtro_empresa(filtros, params, id_empresa, permitidas)

        # mesma janela mensal da view (mes_baixa)
        if data_inicio:
            ini = date.fromisoformat(data_inicio).replace(day=1)
            filtros.append("f.data_baixa >= %s")
            params.append(ini.isoformat())
        if data_fim:
            fim = date.fromisoformat(data_fim)
            prox_mes = (fim.replace(day=1) + timedelta(days=32)).replace(day=1)
            filtros.append("f.data_baixa < %s")
            params.append(prox_mes.isoformat())

        sql = f"""
            SELECT
                f.*,
                COALESCE(NULLIF((
                    SELECT SUM(r.valor_pago) FROM vw_bi_financeiro_recebimento r WHERE r.codigo_titulo = f.codigo_titulo
                ), 0), f.valor_total) AS valor_pago_calc
            FROM vw_bi_financeiro_titulo f
            WHERE {' AND '.join(filtros)}
            ORDER BY f.data_baixa, f.codigo_titulo
        """
        cursor.execute(sql, params)
        rows = cursor.fetchall()

        # nomes (empresa e pessoa) só dos ids presentes
        ids_empresa = sorted({str(r["id_empresa"]) for r in rows if r.get("id_empresa") not in (None, "")})
        nomes_empresa: dict = {}
        if ids_empresa:
            cursor.execute(
                f"SELECT * FROM dim_empresa WHERE codigo_empresa IN ({','.join(['%s'] * len(ids_empresa))})",
                ids_empresa,
            )
            for e in cursor.fetchall():
                nome = next((e[c] for c in ["nome_fantasia", "razao_social", "nome_empresa", "nome", "fantasia", "descricao"] if e.get(c)), None)
                nomes_empresa.setdefault(str(e["codigo_empresa"]), nome)
        nomes_pessoa = _nomes_pessoas(cursor, {r.get("id_pessoa") for r in rows})

        for row in rows:
            pago = float(row.pop("valor_pago_calc") or 0)
            tipo = row.get("tipo_titulo")
            sinal = 1 if tipo == "RECEBER" else -1 if tipo == "PAGAR" else 0
            row["valor_total"] = sinal * pago
            row["valor_pago"] = pago
            row["codigo"] = row.get("codigo_titulo")
            row["nome_empresa"] = nomes_empresa.get(str(row.get("id_empresa")))
            row["nome_pessoa"] = nomes_pessoa.get(str(row.get("id_pessoa")))
            if not row.get("descricao"):
                row["descricao"] = row.get("descricao_conta_resultado")
            if not row.get("origem"):
                row["origem"] = tipo
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