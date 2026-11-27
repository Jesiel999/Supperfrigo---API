from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from database.mysql_connection import connection_mysql
from auth.router import get_current_user
from datetime import date, timedelta
from routers.helpers_router import  (
    _empresas_permitidas,
    _aplicar_filtro_empresa,
    _in
)

router = APIRouter()

@router.get("/pmp")
def get_pmp(
    id_empresa: Optional[str] = Query(None),
    id_pessoa:  Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim:  Optional[str] = Query(None),
    dias_atraso_min: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """
    Retorna registros de prazo médio de pagamento da view vw_bi_pmp,
    restrito às empresas que o usuário logado pode ver.
    """
    conn   = connection_mysql()
    cursor = conn.cursor(dictionary=True)

    try:
        filtros = []
        params  = []

        permitidas = _empresas_permitidas(current_user)
        _aplicar_filtro_empresa(filtros, params, id_empresa, permitidas)

        if id_pessoa:
            filtros.append("id_pessoa = %s")
            params.append(id_pessoa)

        if data_inicio:
            filtros.append("data_movimentacao >= %s")
            params.append(data_inicio)

        if data_fim:
            filtros.append("data_movimentacao <= %s")
            params.append(data_fim)

        if dias_atraso_min is not None:
            filtros.append("dias_pagamento >= %s")
            params.append(dias_atraso_min)

        where = f"WHERE {' AND '.join(filtros)}" if filtros else ""

        cursor.execute(
            f"SELECT * FROM vw_bi_pmp {where}",
            params,
        )
        rows = cursor.fetchall()

        for row in rows:
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
