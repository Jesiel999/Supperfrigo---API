from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from database.mysql_connection import connection_mysql
from auth.router import get_current_user
from datetime import date, timedelta
import re, sys, shutil
from routers.helpers_router import  (
    _empresas_permitidas,
    _aplicar_filtro_empresa,
    _in
)

router = APIRouter()
 
@router.get("/pessoas")
def get_pessoas_filtro(
    id_empresa: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Pessoas (clientes/fornecedores) com títulos no período — alimenta o filtro de DRE e FCP."""
    conn = connection_mysql()
    cursor = conn.cursor(dictionary=True)
 
    try:
        filtros = [
            "f.tenant_id = %s",
            "f.tipo_titulo IN ('RECEBER','PAGAR')",
            "UPPER(f.descricao_situacao) <> 'CANCELADO'",
            "f.id_pessoa IS NOT NULL",
            "f.id_pessoa <> ''",
        ]
        params = [current_user["tenant_id"]]
 
        permitidas = _empresas_permitidas(current_user)
        _aplicar_filtro_empresa(filtros, params, id_empresa, permitidas)
 
        if data_inicio:
            ini = date.fromisoformat(data_inicio).replace(day=1)
            filtros.append("f.data_competencia >= %s")
            params.append(ini.isoformat())
        if data_fim:
            fim = date.fromisoformat(data_fim)
            prox_mes = (fim.replace(day=1) + timedelta(days=32)).replace(day=1)
            filtros.append("f.data_competencia < %s")
            params.append(prox_mes.isoformat())
 
        sql = f"""
            SELECT t.id_pessoa AS id,
                   (SELECT MAX(p.nome) FROM dim_pessoa p WHERE p.codigo_sances = t.id_pessoa) AS nome
            FROM (
                SELECT DISTINCT f.id_pessoa
                FROM fato_financeiro_titulo f
                WHERE {' AND '.join(filtros)}
            ) t
        """
        cursor.execute(sql, params)
        rows = cursor.fetchall()
 
        data = [{"id": str(r["id"]), "nome": r["nome"] or f"Pessoa {r['id']}"} for r in rows]
        data.sort(key=lambda r: r["nome"].lower())
        return {"total": len(data), "data": data}
 
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


#!/usr/bin/env python3
"""
Troca cores fixas (tema escuro) por variáveis de tema dentro do bloco `styles: [`...`]` de componentes Angular.

Uso:   python theme-codemod.py src/app/**/*.ts          (altera os arquivos; cria .bak)
       python theme-codemod.py --dry-run arquivo.ts     (só mostra quantas trocas faria)
Regras (valor fixo → variável):
  #141922 → var(--modal-bg)      #1a202c → var(--modal-card)     #9ca3af → var(--muted)   #cbd5e1 → var(--text)
  rgba(255,255,255,.04|.05) → var(--tint-1)   .06 → var(--tint-2)   .08|.09|.1 → var(--tint-3)
  rgba(0,0,0,.55|.65) → var(--backdrop)       rgba(0,0,0,.45) → var(--shadow-color)
  #f43f5e → var(--accent) (ou var(--neg) em .neg / .state-erro)   #e11d48 → var(--accent-hover)
  #38bdf8 → var(--info)   #34d399 → var(--pos)   color-scheme:dark → color-scheme:var(--color-scheme)
  color:white → var(--text-strong), exceto em regras com fundo sólido de destaque (botões vermelhos).
Revise o resultado: tudo que não estiver na lista continua como estava.
"""

SIMPLES = [
    (r'color-scheme:\s*dark', 'color-scheme:var(--color-scheme)'),
    (r'#141922\b', 'var(--modal-bg)'),
    (r'#1a202c\b', 'var(--modal-card)'),
    (r'#9ca3af\b', 'var(--muted)'),
    (r'#cbd5e1\b', 'var(--text)'),
    (r'rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*0?\.0[45]\s*\)', 'var(--tint-1)'),
    (r'rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*0?\.06\s*\)', 'var(--tint-2)'),
    (r'rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*0?\.(?:08|09|1|10)\s*\)', 'var(--tint-3)'),
    (r'rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0?\.(?:55|65)\s*\)', 'var(--backdrop)'),
    (r'rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0?\.45\s*\)', 'var(--shadow-color)'),
    (r'#e11d48\b', 'var(--accent-hover)'),
    (r'#38bdf8\b', 'var(--info)'),
    (r'#34d399\b', 'var(--pos)'),
]

REGRA = re.compile(r'([^{}]+)\{([^{}]*)\}')


def tema_regra(m: re.Match, contagem: dict) -> str:
    seletor, corpo = m.group(1), m.group(2)
    novo = corpo
    solido = re.search(r'background:\s*#f43f5e', corpo, re.I) is not None   # botão vermelho: texto branco fica
    if not solido:
        novo = re.sub(r'(?<![\w-])color:\s*white\b', 'color:var(--text-strong)', novo)
    alvo = 'var(--neg)' if re.search(r'\.neg\b|state-erro', seletor) else 'var(--accent)'
    novo = re.sub(r'#f43f5e\b', alvo, novo, flags=re.I)
    if novo != corpo:
        contagem['n'] += 1
    return f'{seletor}{{{novo}}}'


def processar(texto: str):
    a = texto.find('styles: [`')
    if a < 0:
        return texto, 0
    b = texto.find('`],', a)
    css = texto[a:b]
    total = 0
    for padrao, subst in SIMPLES:
        css, n = re.subn(padrao, subst, css, flags=re.I)
        total += n
    cont = {'n': 0}
    css = REGRA.sub(lambda m: tema_regra(m, cont), css)
    total += cont['n']
    return texto[:a] + css + texto[b:], total


def main():
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    dry = '--dry-run' in sys.argv
    for p in args:
        s = open(p, encoding='utf-8').read()
        novo, n = processar(s)
        print(f'{p}: {n} trocas' + (' (dry-run)' if dry else ''))
        if n and not dry:
            shutil.copyfile(p, p + '.bak')
            open(p, 'w', encoding='utf-8').write(novo)


if __name__ == '__main__':
    main()