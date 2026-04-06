from fastapi import FastAPI



app = FastAPI()


@app.get("/", summary="Home route")
def home():
    return {"message": "Hello World"}


@app.get("/profile/{name}", summary="Get user name and age")
def getProfile(name: str, age: int | None = None) :
    return {"name": name, "age": age}

