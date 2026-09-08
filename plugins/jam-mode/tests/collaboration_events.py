"""App Server collaboration events using the installed protocol's field names."""


def event(item, *, thread="thr_fake_001", turn="turn_fake_001", method="item/completed"):
    return {"method": method, "params": {"threadId": thread, "turnId": turn, "item": item}}


def duo_events():
    parent = "thr_fake_001"
    children = ["thr_explorer", "thr_critic"]
    events = []
    for role, child in zip(("explorer", "critic"), children):
        events.append(event({
            "id": f"spawn_{role}", "type": "collabAgentToolCall",
            "tool": "spawnAgent", "status": "completed",
            "senderThreadId": parent, "receiverThreadIds": [child],
            "agentsStates": {child: {"status": "running", "message": None}},
            "prompt": f"Use jam_{role} to investigate the original objective independently.",
            "model": None, "reasoningEffort": None,
        }))
    events.append(event({
        "id": "wait_pair", "type": "collabAgentToolCall",
        "tool": "wait", "status": "completed",
        "senderThreadId": parent, "receiverThreadIds": children,
        "agentsStates": {
            children[0]: {"status": "completed", "message": "Evidence supports approach A."},
            children[1]: {"status": "completed", "message": "Approach A needs boundary check B."},
        },
        "prompt": None, "model": None, "reasoningEffort": None,
    }))
    return events


def final_event(text="parent synthesis"):
    return event({"id": "final", "type": "agentMessage", "phase": "final_answer", "text": text})
