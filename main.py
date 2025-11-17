import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import ArtPrint, Order, OrderItem

app = FastAPI(title="Art Prints Storefront API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Utility helpers
# -----------------------------

def serialize_doc(doc: dict):
    if not doc:
        return doc
    d = {**doc}
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    # Convert any nested ObjectIds
    for k, v in list(d.items()):
        if isinstance(v, ObjectId):
            d[k] = str(v)
    return d


# -----------------------------
# Startup: seed sample prints
# -----------------------------
@app.on_event("startup")
async def seed_data():
    try:
        if db is None:
            return
        count = db.artprint.count_documents({})
        if count == 0:
            samples = [
                {
                    "title": "Sunlit Dunes",
                    "artist": "Ava Linden",
                    "description": "Soft gradients inspired by desert horizons.",
                    "price": 49.0,
                    "size": "12x18 in",
                    "image_url": "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?q=80&w=1200&auto=format&fit=crop",
                    "tags": ["abstract", "minimal"],
                    "in_stock": True,
                    "featured": True,
                },
                {
                    "title": "Coastal Mist",
                    "artist": "Noah Pierce",
                    "description": "Calming blue tones of a foggy shoreline.",
                    "price": 59.0,
                    "size": "16x20 in",
                    "image_url": "https://images.unsplash.com/photo-1501785888041-af3ef285b470?q=80&w=1200&auto=format&fit=crop",
                    "tags": ["landscape", "blue"],
                    "in_stock": True,
                    "featured": True,
                },
                {
                    "title": "City Geometry",
                    "artist": "Mila Ortega",
                    "description": "Architectural lines and morning light.",
                    "price": 45.0,
                    "size": "12x16 in",
                    "image_url": "https://images.unsplash.com/photo-1491553895911-0055eca6402d?q=80&w=1200&auto=format&fit=crop",
                    "tags": ["architecture", "black-white"],
                    "in_stock": True,
                    "featured": False,
                },
                {
                    "title": "Botanical Study",
                    "artist": "Elle Fuji",
                    "description": "Delicate leaves with watercolor textures.",
                    "price": 39.0,
                    "size": "11x14 in",
                    "image_url": "https://images.unsplash.com/photo-1499951360447-b19be8fe80f5?q=80&w=1200&auto=format&fit=crop",
                    "tags": ["botanical", "nature"],
                    "in_stock": True,
                    "featured": False,
                },
            ]
            db.artprint.insert_many(samples)
    except Exception:
        # Fail silently if no database or seeding error
        pass


# -----------------------------
# Health/Test endpoints
# -----------------------------
@app.get("/")
def read_root():
    return {"message": "Art Prints API running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = getattr(db, "name", None) or "Unknown"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    return response


# -----------------------------
# Storefront API
# -----------------------------

class CreatePrintRequest(ArtPrint):
    pass


@app.get("/api/prints")
def list_prints(featured: Optional[bool] = None) -> List[dict]:
    filt = {}
    if featured is not None:
        filt["featured"] = featured
    docs = get_documents("artprint", filt)
    return [serialize_doc(d) for d in docs]


@app.post("/api/prints")
def create_print(payload: CreatePrintRequest):
    try:
        new_id = create_document("artprint", payload)
        doc = db.artprint.find_one({"_id": ObjectId(new_id)})
        return serialize_doc(doc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class CreateOrderRequest(BaseModel):
    customer_name: str
    customer_email: str
    shipping_address: str
    items: List[OrderItem]


@app.post("/api/orders")
def create_order(payload: CreateOrderRequest):
    # Validate items and compute total from DB to prevent tampering
    if not payload.items:
        raise HTTPException(status_code=400, detail="Order must contain at least one item")

    total = 0.0
    normalized_items = []
    for item in payload.items:
        try:
            doc = db.artprint.find_one({"_id": ObjectId(item.print_id)})
        except Exception:
            doc = None
        if not doc:
            raise HTTPException(status_code=404, detail=f"Print not found: {item.print_id}")
        if not doc.get("in_stock", True):
            raise HTTPException(status_code=400, detail=f"Print out of stock: {doc.get('title')}")
        price = float(doc.get("price", 0))
        total += price * item.quantity
        normalized_items.append({
            "print_id": str(doc["_id"]),
            "title": doc.get("title"),
            "price": price,
            "quantity": item.quantity,
        })

    order = Order(
        customer_name=payload.customer_name,
        customer_email=payload.customer_email,
        shipping_address=payload.shipping_address,
        items=[OrderItem(**{"print_id": it["print_id"], "quantity": it["quantity"]}) for it in normalized_items],
        total=round(total, 2),
        status="pending",
    )

    try:
        order_id = create_document("order", order)
        saved = db.order.find_one({"_id": ObjectId(order_id)})
        # Attach expanded items for response convenience
        saved_serialized = serialize_doc(saved)
        saved_serialized["items_detailed"] = normalized_items
        return saved_serialized
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
