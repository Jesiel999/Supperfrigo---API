
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.sances.financeiro import (
    fcp_router,
    dre_router,
    fc_router,
    inadimplencia_router,
    pmp_router,
    pmr_router,
    pagar_router,
    receber_router
)

from routers import (
    chips_router,
    colaboradores_router,
    dropdowns_router,
    equipamentos_router,
    pipeline_router,
    financeiro_router,
    usuarios_router,
    permissoes_router,
    empresas_router,
    menu_router,
    telemetria_router,
    estoque_router,
    cadastros_router,
    pessoa_router,
    home_router,
    termos_router,
    estoque_veiculos_router,
    pos_venda_router
)

from auth.router import router as auth_router


app = FastAPI(
    title="ETL API",
    description="API para execução e monitoramento do pipeline ETL",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(menu_router.router, prefix="", tags=["Menu"])
app.include_router(pipeline_router.router, prefix="/pipeline", tags=["Pipeline"])

app.include_router(financeiro_router.router, prefix="/financeiro", tags=["Financeiro"])
app.include_router(inadimplencia_router.router, prefix="/financeiro", tags=["Inadimplência"])
app.include_router(pagar_router.router, prefix="/financeiro", tags=["Pagar"])
app.include_router(receber_router.router, prefix="/financeiro", tags=["Receber"])
app.include_router(pmp_router.router, prefix="/financeiro", tags=["PMP"])
app.include_router(pmr_router.router, prefix="/financeiro", tags=["PMR"])
app.include_router(dre_router.router, prefix="/financeiro", tags=["DRE"])
app.include_router(fcp_router.router, prefix="/financeiro", tags=["FCP"])
app.include_router(fc_router.router, prefix="/financeiro", tags=["FC"])

app.include_router(estoque_router.router, prefix="/estoque", tags=["Estoque"])
app.include_router(estoque_veiculos_router.router, prefix="/estoque_veiculos", tags=["Estoque Veículos"])
app.include_router(pos_venda_router.router, prefix="/pos_venda", tags=["Pos Venda"])
app.include_router(telemetria_router.router, prefix="/telemetria", tags=["Telemetria"])
app.include_router(usuarios_router.router, prefix="/usuarios", tags=["Usuarios"])
app.include_router(permissoes_router.router, prefix="/permissoes", tags=["Permissoes"])
app.include_router(empresas_router.router, prefix="/empresas", tags=["Empresas"])
app.include_router(home_router.router, prefix="/home", tags=["Home"])
app.include_router(termos_router.router, prefix="/api/termos", tags=["Termos"])

app.include_router(equipamentos_router.router)
app.include_router(chips_router.router)
app.include_router(dropdowns_router.router)
app.include_router(colaboradores_router.router)
app.include_router(pessoa_router.router)
 
app.include_router(cadastros_router.router_marcas)
app.include_router(cadastros_router.router_modelos)
app.include_router(cadastros_router.router_toners)
app.include_router(cadastros_router.router_departamentos)


@app.get("/")
def root():
    return {"status": "ETL API online"}
