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

@router.get("/receber")
def get_receber(
    id_empresa: Optional[str] = Query(None),
    id_pessoa: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):

    """
    Retorna registros do Receber evidenciando a taxa de recebimento
    """

    conn = connection_mysql()
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
            filtros.append("data_vencimento >= %s")
            params.append(data_inicio)

        if data_fim:
            filtros.append("data_vencimento <= %s")
            params.append(data_fim)

        where = f"WHERE {' AND '.join(filtros)}" if filtros else ""

        cursor.execute(
            f"SELECT * FROM vw_bi_receber {where}",
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
