"""HTTP and WebSocket API."""

from fastapi.testclient import TestClient

from dsky import server


def client():
    server.sim = server.Sim()
    return TestClient(server.app)


def test_index_and_tables():
    with client() as c:
        assert c.get("/").status_code == 200
        nouns = c.get("/api/nouns").json()
        assert any(n["number"] == 63 for n in nouns)
        verbs = c.get("/api/verbs").json()
        assert any(v["number"] == 37 for v in verbs)
        assert c.get("/api/programs").status_code == 200
        assert c.get("/api/alarms").status_code == 200


def test_key_and_sequence_endpoints():
    with client() as c:
        s = c.post("/api/keys", json={"sequence": "V16N36E"}).json()
        assert s["display"]["verb"] == "16" and s["display"]["noun"] == "36"
        s = c.post("/api/key", json={"key": "VERB"}).json()
        assert s["keyboard"]["entry"] == "verb"
        assert c.post("/api/key", json={"key": "bogus"}).status_code == 400
        assert c.post("/api/keys", json={"sequence": "VXE"}).status_code == 400


def test_uplink_lights_the_lamp():
    with client() as c:
        s = c.post("/api/keys", json={"sequence": "V16N36E", "uplink": True}).json()
        assert s["display"]["lamps"]["UPLINK ACTY"]
        assert any("UPLINK" in e["text"] for e in s["events"])


def test_sim_controls():
    with client() as c:
        s = c.post("/api/sim", json={"rr_switch": "AUTO", "rate": 4}).json()
        assert s["rr_switch"] == "AUTO" and s["rate"] == 4
        assert c.post("/api/sim", json={"rr_switch": "SIDEWAYS"}).status_code == 400
        s = c.post("/api/sim", json={"reset": True}).json()
        assert s["rr_switch"] == "LGC" and s["rate"] == 1


def test_websocket_pushes_state_and_accepts_keys():
    with client() as c:
        with c.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert "display" in first
            ws.send_json({"sequence": "V16N36E"})
            s = ws.receive_json()
            assert s["display"]["verb"] == "16"
