from typing import Optional

# ── Helper: aplica a regra básica de acesso por empresa ─────────────
def _empresas_permitidas(current_user: dict) -> Optional[list]:
    """
    None  = usuário sem restrição no JWT (vê todas as empresas do dim_empresa)
    list  = lista de códigos (str) que o usuário PODE ver — qualquer coisa
            fora disso deve ser bloqueada, mesmo que o cliente peça.
    """
    empresas = current_user.get("empresas") or []
    if not empresas:
        return None
    return [str(e["codigo"]) for e in empresas]


def _aplicar_filtro_empresa(filtros: list, params: list, id_empresa: Optional[str], permitidas: Optional[list]):
    """
    Regra central: se o usuário tem restrição, SEMPRE filtra pelo que ele
    pode ver — ignora ou valida o id_empresa vindo da query string.
    Nunca confia no client para decidir o que ele pode ver.
    """
    if permitidas is not None:
        if id_empresa:
            if id_empresa not in permitidas:
                raise HTTPException(status_code=403, detail="Sem acesso a esta empresa")
            filtros.append("id_empresa = %s")
            params.append(id_empresa)
        else:
            placeholders = ",".join(["%s"] * len(permitidas))
            filtros.append(f"id_empresa IN ({placeholders})")
            params.extend(permitidas)
    elif id_empresa:
        filtros.append("id_empresa = %s")
        params.append(id_empresa)

def _nomes_pessoas(cursor, ids, lote: int = 1000) -> dict:
    ids = sorted({str(i) for i in ids if i not in (None, "")})
    nomes: dict = {}
    for k in range(0, len(ids), lote):
        parte = ids[k:k + lote]
        cursor.execute(
            f"""SELECT codigo_sances, MAX(nome) AS nome
                FROM dim_pessoa
                WHERE codigo_sances IN ({','.join(['%s'] * len(parte))})
                GROUP BY codigo_sances""",
            parte,
        )
        for p in cursor.fetchall():
            nomes[str(p["codigo_sances"])] = p["nome"]
    return nomes


def _in(n: int) -> str:
    return ",".join(["%s"] * n)
    