// Coach Game SDK: Unity reference client. One script, no packages beyond UnityEngine.
// Drop it on an empty GameObject, fill Base Url / Live Id / Consent Id from the Coach page
// (Live card > Game SDK), add your landmarks, and subscribe to the events.
//
// What it does every PostInterval seconds:
//   POST {baseUrl}/api/game/{liveId}/state   with player, objective, landmarks (projected to screen), queued events
//   GET  {baseUrl}/api/game/{liveId}/directives and raises OnCallout / OnPoint / OnRoute / OnReaction / OnTasks
//
// Call ReportEvent("fell") (or any reaction trigger: missed_jump, dumb_play, ignored_callout, whiff,
// near_death, clutch, rizz_detected, slow_reaction) and Coach reacts with no model round trip.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.Networking;

[Serializable] public class CoachLandmark { public string id; public string label; public Transform target; }
[Serializable] public class CoachPointEvent : UnityEvent<string, string, Transform> { }   // landmarkId, label, target (null if unknown)
[Serializable] public class CoachRouteEvent : UnityEvent<List<CoachLandmark>> { }
[Serializable] public class CoachTextEvent : UnityEvent<string> { }
[Serializable] public class CoachReactionEvent : UnityEvent<string, string, string> { }   // trigger, line, imageUrl
[Serializable] public class CoachTasksEvent : UnityEvent<List<string>> { }

public class CoachClient : MonoBehaviour
{
    [Header("Connection (copy from the Coach page, Live card > Game SDK)")]
    public string baseUrl = "http://127.0.0.1:8000";
    public string liveId = "";
    public string consentId = "";
    [Tooltip("Seconds between state posts. 1 is plenty; Coach's watch tick is 4 s.")]
    public float postInterval = 1.0f;

    [Header("What Coach knows about your game")]
    public string gameName = "My Game";
    public Transform player;
    public Camera playerCamera;
    [TextArea] public string objective = "";
    public int playerHp = 100;
    public string playerState = "playing";
    public List<CoachLandmark> landmarks = new List<CoachLandmark>();

    [Header("Coach directives")]
    public CoachTextEvent OnCallout;          // say it with your TTS or show it in-world
    public CoachPointEvent OnPoint;           // draw an arrow at the landmark's transform
    public CoachRouteEvent OnRoute;           // draw a path through these landmarks in order
    public CoachReactionEvent OnReaction;     // show the meme card (imageUrl is absolute) and play a sound
    public CoachTasksEvent OnTasks;           // the task list

    public bool Connected { get; private set; }
    public string LastError { get; private set; } = "";

    readonly List<string> queuedEvents = new List<string>();
    double lastCalloutAt = -1, lastReactionTs = -1, lastPointerCreated = -1, lastRouteCreated = -1;

    public void ReportEvent(string type, string detail = "")
    {
        queuedEvents.Add("{\"type\":" + Q(type) + ",\"detail\":" + Q(detail) + "}");
    }

    void OnEnable() { StartCoroutine(Loop()); }

    IEnumerator Loop()
    {
        var wait = new WaitForSeconds(Mathf.Max(0.25f, postInterval));
        while (enabled)
        {
            if (string.IsNullOrEmpty(liveId)) { yield return wait; continue; }
            yield return PostState();
            yield return PollDirectives();
            yield return wait;
        }
    }

    // ---- state out ----
    IEnumerator PostState()
    {
        var sb = new StringBuilder();
        sb.Append("{\"game\":").Append(Q(gameName));
        if (player != null)
        {
            var p = player.position;
            sb.Append(",\"player\":{\"pos\":[").Append(F(p.x)).Append(',').Append(F(p.y)).Append(',').Append(F(p.z)).Append(']')
              .Append(",\"yaw\":").Append(F(player.eulerAngles.y)).Append(",\"hp\":").Append(playerHp)
              .Append(",\"state\":").Append(Q(playerState)).Append('}');
        }
        sb.Append(",\"objective\":").Append(Q(objective));
        sb.Append(",\"landmarks\":[");
        bool first = true;
        foreach (var lm in landmarks)
        {
            if (lm == null || lm.target == null || string.IsNullOrEmpty(lm.id)) continue;
            if (!first) sb.Append(','); first = false;
            var w = lm.target.position;
            bool visible = false; float sx = 0, sy = 0; string dir = "";
            var cam = playerCamera != null ? playerCamera : Camera.main;
            if (cam != null)
            {
                var v = cam.WorldToViewportPoint(w);
                visible = v.z > 0 && v.x >= 0 && v.x <= 1 && v.y >= 0 && v.y <= 1;
                sx = Mathf.Clamp01(v.x); sy = Mathf.Clamp01(1f - v.y);   // Coach uses y down from the top
                if (!visible)
                {
                    var local = cam.transform.InverseTransformPoint(w);
                    if (local.z < 0 && Mathf.Abs(local.x) < Mathf.Abs(local.z)) dir = "behind";
                    else if (local.x < 0) dir = "left"; else dir = "right";
                }
            }
            sb.Append("{\"id\":").Append(Q(lm.id)).Append(",\"label\":").Append(Q(string.IsNullOrEmpty(lm.label) ? lm.id : lm.label))
              .Append(",\"pos\":[").Append(F(w.x)).Append(',').Append(F(w.y)).Append(',').Append(F(w.z)).Append(']')
              .Append(",\"visible\":").Append(visible ? "true" : "false");
            if (visible) sb.Append(",\"screen\":[").Append(F(sx)).Append(',').Append(F(sy)).Append(']');
            if (!string.IsNullOrEmpty(dir)) sb.Append(",\"dir\":").Append(Q(dir));
            sb.Append('}');
        }
        sb.Append("],\"events\":[").Append(string.Join(",", queuedEvents)).Append("]}");
        queuedEvents.Clear();

        using (var req = new UnityWebRequest(baseUrl + "/api/game/" + liveId + "/state", "POST"))
        {
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(sb.ToString()));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.SetRequestHeader("X-Coach-Consent", consentId);
            yield return req.SendWebRequest();
            Connected = req.result == UnityWebRequest.Result.Success;
            LastError = Connected ? "" : req.responseCode + " " + req.error + " " + req.downloadHandler.text;
        }
    }

    // ---- directives in ----
    IEnumerator PollDirectives()
    {
        using (var req = UnityWebRequest.Get(baseUrl + "/api/game/" + liveId + "/directives"))
        {
            yield return req.SendWebRequest();
            if (req.result != UnityWebRequest.Result.Success) yield break;
            Apply(req.downloadHandler.text);
        }
    }

    [Serializable] class Directives { public Overlay overlay; public string speak; public double speak_at; }
    [Serializable] class Overlay { public string callout; public double callout_at; public List<Pointer> pointers; public List<Waypoint> route; public Reaction reaction; public List<Task> tasks; }
    [Serializable] class Pointer { public float x, y; public string label, direction, landmark; public double created; }
    [Serializable] class Waypoint { public int n; public float x, y; public string label, landmark; public double created; }
    [Serializable] class Reaction { public string trigger, line, image, sound; public double ts; }
    [Serializable] class Task { public string text; public bool done; }

    void Apply(string json)
    {
        Directives d;
        try { d = JsonUtility.FromJson<Directives>(json); } catch (Exception e) { LastError = e.Message; return; }
        if (d == null || d.overlay == null) return;
        var ov = d.overlay;
        if (!string.IsNullOrEmpty(ov.callout) && ov.callout_at > lastCalloutAt) { lastCalloutAt = ov.callout_at; OnCallout?.Invoke(ov.callout); }
        if (ov.pointers != null)
            foreach (var p in ov.pointers)
                if (p.created > lastPointerCreated) { lastPointerCreated = p.created; OnPoint?.Invoke(p.landmark ?? "", p.label ?? "", Find(p.landmark)); }
        if (ov.route != null && ov.route.Count > 0 && ov.route[0].created > lastRouteCreated)
        {
            lastRouteCreated = ov.route[0].created;
            var steps = new List<CoachLandmark>();
            foreach (var w in ov.route) steps.Add(new CoachLandmark { id = w.landmark ?? "", label = w.label ?? "", target = Find(w.landmark) });
            OnRoute?.Invoke(steps);
        }
        if (ov.reaction != null && ov.reaction.ts > lastReactionTs)
        {
            lastReactionTs = ov.reaction.ts;
            OnReaction?.Invoke(ov.reaction.trigger, ov.reaction.line, baseUrl + ov.reaction.image);
        }
        if (ov.tasks != null) { var t = new List<string>(); foreach (var x in ov.tasks) t.Add((x.done ? "[x] " : "[ ] ") + x.text); OnTasks?.Invoke(t); }
    }

    Transform Find(string id)
    {
        if (string.IsNullOrEmpty(id)) return null;
        foreach (var lm in landmarks) if (lm != null && lm.id == id) return lm.target;
        return null;
    }

    static string F(float v) { return v.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture); }
    static string Q(string s) { return "\"" + (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", " ") + "\""; }
}
