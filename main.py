from fastapi import FastAPI, Request, Form, File, UploadFile, APIRouter
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from tortoise import fields, Model
from tortoise.contrib.fastapi import register_tortoise
from secrets import choice
from random import randint
from pathlib import Path
from loguru import logger
from io import BytesIO
from config import database_url, port
import uvicorn, os, sys, qrcode, zipfile

logger.add(
    sys.stdout,
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | {level} | <level>{message}</level>",
)

app = FastAPI(
    docs_url=None,
    title="files uploader",
    description="for donations: https://paypal.me/itayki.",
    version="1.0",
)
downloads_folder = "files_dir"
max_file_size = 700000000
file_id_allowed_characters = "abcdefghijklmnopqrstuvwxyz0123456789"


class Files(Model):
    file_id = fields.CharField(max_length=20, pk=True)
    file_location = fields.TextField()
    file_folder = fields.TextField(default=downloads_folder)
    file_name = fields.TextField()
    views = fields.IntField()
    created_at = fields.DatetimeField(auto_now_add=True)


def make_zip(file, filename: str):
    with zipfile.ZipFile(
        f"{downloads_folder}/{filename}.zip",
        "w",
        compression=zipfile.ZIP_DEFLATED,
        allowZip64=True,
    ) as zipthefile:
        zipthefile.write(file)


async def check_if_file_id_exists(file_id: str):
    return await Files.exists(file_id=file_id)


def gen_file_id_one():
    the_file_id_length = randint(4, 20)
    file_id = "".join(
        choice(file_id_allowed_characters) for i in range(the_file_id_length)
    )
    return file_id


async def gen_valid_file_id():
    while True:
        file_id = gen_file_id_one()
        check_file_id_exists = await check_if_file_id_exists(file_id=file_id)
        if not check_file_id_exists:
            break
    return file_id


async def check_file_size(file_size: int):
    if file_size > max_file_size:
        raise HTTPException(status_code=400, detail="the file is bigger than 700MB")
    else:
        return True


async def upload_the_file_db(file, file_size: int, host):
    await check_file_size(file_size=file_size)
    filename = file.filename
    file_id = await gen_valid_file_id()
    check_suffix_one = Path(filename).suffix
    check_suffix_two = check_suffix_one if check_suffix_one != "" else None
    if check_suffix_two:
        if not check_suffix_two.startswith("."):
            check_suffix_two = "." + check_suffix_two
        file_location = f"{downloads_folder}/{file_id}{check_suffix_two}"
        the_file_name = f"{file_id}{check_suffix_two}"
    else:
        file_location = f"{downloads_folder}/{file_id}"
        the_file_name = f"{file_id}"
    read_file = await file.read()
    with open(f"{file_location}", "wb") as writefile:
        writefile.write(read_file)
    make_zip(file=file_location, filename=the_file_name)
    os.remove(file_location)
    await Files.create(
        file_id=file_id,
        file_location=file_location,
        file_folder=downloads_folder,
        file_name=the_file_name,
        views=0,
    )
    return {
        "file_id": file_id,
        "download_url": f"{host}/download/{file_id}",
        "qr_code": f"{host}/qr/{file_id}",
    }


async def get_file_stats_db(file_id: str, host):
    thefileid = file_id.lower()
    check_file_id_exists = await check_if_file_id_exists(file_id=file_id)
    if not check_file_id_exists:
        raise HTTPException(status_code=404, detail="the file id is not exists")
    else:
        check_file_db = await Files.get(file_id=file_id)
        return {
            "file_id": check_file_db.file_id,
            "link": f"{host}/download/{thefileid}",
            "views": check_file_db.views,
            "created_at": check_file_db.created_at,
            "qr_code": f"{host}/qr/{thefileid}",
        }


async def get_the_file_download(file_id: str):
    thefileid = file_id.lower()
    check_file_id_exists = await check_if_file_id_exists(file_id=thefileid)
    if not check_file_id_exists:
        raise HTTPException(status_code=404, detail="the file id is not exists")
    else:
        get_the_file_id_db = await Files.get(file_id=thefileid)
        get_the_file_location = get_the_file_id_db.file_location + ".zip"
        get_the_file_name = get_the_file_id_db.file_name + ".zip"
        theviews = int(get_the_file_id_db.views) + 1
        await Files.filter(file_id=thefileid).update(views=theviews)
        return FileResponse(
            get_the_file_location,
            media_type="application/octet-stream",
            filename=get_the_file_name,
        )


async def get_download_qr_code(file_id: str, host):
    thefileid = file_id.lower()
    check_file_id_exists = await check_if_file_id_exists(file_id=thefileid)
    if not check_file_id_exists:
        raise HTTPException(status_code=404, detail="the file id is not exists")
    else:
        thelink = f"{host}/qr/{thefileid}"
        make_qr_code = qrcode.make(thelink)
        bytes_qr_code = BytesIO()
        make_qr_code.save(bytes_qr_code)
        qr_code_result = BytesIO(bytes_qr_code.getvalue())
        return StreamingResponse(qr_code_result, media_type="image/jpeg")


async def get_files_count():
    return await Files.all().count()


@app.on_event("startup")
async def app_startup_actions():
    try:
        os.stat(downloads_folder)
    except:
        os.mkdir(downloads_folder)


templates = Jinja2Templates(directory="templates")


@app.get("/", include_in_schema=False)
async def homepage(request: Request):
    return templates.TemplateResponse("index.html", context={"request": request})


@app.post("/", include_in_schema=False)
async def homepage_post(request: Request, file: UploadFile = File(...)):
    thehost = request.headers["host"]
    thefilesize = request.headers["Content-Length"]
    thefilesize = int(thefilesize)
    try:
        upload_file_to_the_db = await upload_the_file_db(
            file=file, file_size=thefilesize, host=thehost
        )
        res_file_id = upload_file_to_the_db["file_id"]
        res_download_url = upload_file_to_the_db["download_url"]
        res_qr_code = upload_file_to_the_db["qr_code"]
        result = f"the file id: {res_file_id}, the download url: {res_download_url}, qr code: {res_qr_code}"
        thetype = "the file info"
    except Exception as e:
        result = e
        thetype = type(e).__name__
        if thetype == "HTTPException":
            result = e.detail
    return templates.TemplateResponse(
        "results.html",
        context={"request": request, "type": thetype, "result": result},
    )


@app.get("/get", include_in_schema=False)
async def statspage(request: Request):
    return templates.TemplateResponse("stats.html", context={"request": request})


@app.post("/get", include_in_schema=False)
async def statspage_post(request: Request, file_id: str = Form(...)):
    thehost = request.headers["host"]
    try:
        get_file_db_stats = await get_file_stats_db(file_id=file_id, host=thehost)
        res_file_id = get_file_db_stats["file_id"]
        res_download_url = get_file_db_stats["link"]
        res_views = get_file_db_stats["views"]
        res_qr_code = get_file_db_stats["qr_code"]
        res_created_at = get_file_db_stats["created_at"]
        result = f"the file id: {res_file_id}, the download url: {res_download_url}, created at {res_created_at}, the views: {res_views}, the qr code link: {res_qr_code}"
        thetype = "the file stats"
    except Exception as e:
        result = e
        thetype = type(e).__name__
        if thetype == "HTTPException":
            result = e.detail
    return templates.TemplateResponse(
        "results.html",
        context={"request": request, "type": thetype, "result": result},
    )


@app.get("/docs", include_in_schema=False)
async def get_api_docs():
    return get_swagger_ui_html(openapi_url=app.openapi_url, title=app.title + " docs")


apirouter = APIRouter(prefix="/api")


@apirouter.post("/upload")
async def upload_the_file(request: Request, file: UploadFile = File(...)):
    thehost = request.headers["host"]
    thefilesize = request.headers["Content-Length"]
    thefilesize = int(thefilesize)
    upload_the_file = await upload_the_file_db(
        file=file, file_size=thefilesize, host=thehost
    )
    return upload_the_file


@apirouter.api_route("/stats", methods=["POST", "GET"])
async def get_file_stats(file_id: str, request: Request):
    thehost = request.headers["host"]
    get_the_file_id_stats = await get_file_stats_db(file_id=file_id, host=thehost)
    return get_the_file_id_stats


@apirouter.api_route("/all", methods=["POST", "GET"])
async def get_the_files_count():
    return {"count": await get_files_count()}


@app.get("/download/{file_id}")
async def download_the_file(file_id: str):
    downloadfiledb = await get_the_file_download(file_id=file_id)
    return downloadfiledb


@app.api_route("/qr/{file_id}", methods=["POST", "GET"])
async def generate_qr_code(file_id: str, request: Request):
    thehost = request.headers["host"]
    get_the_download_qr_code = await get_download_qr_code(file_id=file_id, host=thehost)
    return get_the_download_qr_code


app.include_router(apirouter)
register_tortoise(
    app,
    db_url=database_url,
    modules={"models": [__name__]},
    generate_schemas=True,
)
uvicorn.run(app=app, host="0.0.0.0", port=port)
