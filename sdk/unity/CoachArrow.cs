// A world-space arrow that points at whatever Coach pointed at. Wire CoachClient.OnPoint to Show,
// and put this on a small arrow mesh parented to the player (or the camera). Hides itself after
// `seconds`. For a route, call ShowRoute and it walks the waypoints as the player reaches them.
using System.Collections.Generic;
using UnityEngine;

public class CoachArrow : MonoBehaviour
{
    public Transform follow;            // the player or camera the arrow floats in front of
    public Vector3 offset = new Vector3(0, 1.6f, 1.2f);
    public float seconds = 12f;
    public float reachDistance = 2f;    // route: advance to the next waypoint within this distance of the current one
    public TextMesh label;              // optional

    Transform target; float until; readonly Queue<Transform> route = new Queue<Transform>();
    Renderer[] renderers;

    void Awake() { renderers = GetComponentsInChildren<Renderer>(); SetVisible(false); }

    public void Show(string landmarkId, string text, Transform t)
    {
        route.Clear();
        target = t; until = Time.time + seconds;
        if (label != null) label.text = string.IsNullOrEmpty(text) ? landmarkId : text;
        SetVisible(target != null);
    }

    public void ShowRoute(List<CoachLandmark> steps)
    {
        route.Clear();
        foreach (var s in steps) if (s != null && s.target != null) route.Enqueue(s.target);
        if (route.Count == 0) return;
        target = route.Dequeue(); until = Time.time + seconds * steps.Count;
        if (label != null) label.text = "1";
        SetVisible(true);
    }

    void LateUpdate()
    {
        if (target == null) return;
        if (Time.time > until) { target = null; route.Clear(); SetVisible(false); return; }
        if (follow != null) transform.position = follow.TransformPoint(offset);
        var dir = target.position - transform.position; dir.y *= 0.3f;
        if (dir.sqrMagnitude > 0.0001f) transform.rotation = Quaternion.Slerp(transform.rotation, Quaternion.LookRotation(dir), Time.deltaTime * 8f);
        if (follow != null && route.Count > 0 && Vector3.Distance(follow.position, target.position) < reachDistance)
        {
            target = route.Dequeue();
            if (label != null) label.text = (int.TryParse(label.text, out var n) ? n + 1 : 2).ToString();
        }
        if (label != null && follow != null) label.transform.rotation = Quaternion.LookRotation(label.transform.position - follow.position);
    }

    void SetVisible(bool v) { foreach (var r in renderers) r.enabled = v; if (label != null) label.gameObject.SetActive(v); }
}
