# Photobooth Gallery

## Purpose

Photobooth Gallery will be a separately hosted web app for browsing photos from one or more photobooth installations. It should remain available when no booths are running, so visitors can browse previously uploaded sessions and TVs can continue displaying a session slideshow.

This folder currently contains the design plan only. The implementation and exact deployment platform have not been selected.

## Planned capabilities

- Receive photos from configured photobooth installations through an authenticated upload API. Booths should be able to retry uploads after a network interruption.
- List visible, active sessions and let visitors browse their photos.
- Provide a full-screen slideshow for a paired TV display, suitable for a browser or a Raspberry Pi Zero connected to a TV.
- Update an open slideshow when new photos arrive in its session.
- Let a browser client upvote each photo once. A database uniqueness rule should prevent duplicate votes from the same client identifier.
- Let a paired TV upvote the photo currently on screen, once for each automatic slideshow appearance. A later automatic appearance makes that TV eligible to vote for the photo again.
- Use vote totals to increase a photo's relative chance of appearing in the slideshow, while keeping new or unvoted photos in rotation and avoiding immediate repeats.
- Let visitors report photos for review. Hide a photo from slideshows when it reaches a configurable report threshold, while retaining it for moderator review.
- Provide a moderation view for reviewing reported photos and deciding whether to restore or remove them.

## Proposed architecture

- **Backend:** Python with Flask, building on the existing photobooth codebase and its upload protocol where practical.
- **Production serving:** A WSGI server such as Gunicorn behind a reverse proxy or managed hosting platform. Do not expose Flask's development server in production.
- **Database:** PostgreSQL for session and photo metadata, vote records, report records, moderation status, and gallery configuration.
- **Image storage:** Object storage or a dedicated persistent media store, separate from the database and outside the web root. Store generated identifiers rather than trusting uploaded filenames.
- **Browser UI:** Server-rendered pages with focused JavaScript for browsing, voting, reporting, moderation, and slideshow playback. A separate frontend framework is not required for the first version.
- **Live updates:** Server-Sent Events (SSE) can notify gallery and slideshow pages of session changes. Clients then fetch updated photo metadata. Short polling is a simpler fallback for an initial implementation.
- **TV client:** A URL-driven, full-screen web slideshow that reconnects and refreshes if its network connection drops. It should run on low-power devices such as Raspberry Pi Zero.
- **TV pairing:** Each Pi opens the same stable gallery URL. A new or unpaired TV displays a setup code; an administrator enters that code in the gallery admin interface and assigns a session to the TV. Pairing gives the display a stable identity, so it can show its assigned session on later visits without a session-specific URL. Setup codes should expire after pairing or timeout; the TV should retain a separate revocable device credential.
- **GPIO controls:** A small local Python service can handle GPIO buttons and device setup while the browser renders the slideshow. Buttons can request an upvote or step backward/forward. The gallery remains the authority for vote eligibility and vote counts.

The web app should be deployed independently from the booth service. The photobooth remains responsible for capture and its persistent upload queue; the gallery handles shared browsing, slideshow playback, voting, reporting, and moderation. This keeps photo browsing available when booth hardware is offline.

## Initial repository structure

The following is a proposed structure for the gallery implementation. Keep the first version small and split components further only when the implementation needs it.

```text
gallery/
├── README.md
├── requirements.txt
├── wsgi.py                 # Production WSGI entry point
├── config.example.env      # Example settings; secrets stay out of Git
├── app/
│   ├── __init__.py         # Flask app factory and configuration
│   ├── routes/             # Public pages, upload API, moderation API
│   ├── models.py           # Sessions, photos, votes, reports
│   ├── slideshow.py        # Weighted photo selection
│   ├── storage.py          # Image storage adapter
│   ├── templates/          # Gallery, slideshow, moderation pages
│   └── static/             # CSS, JavaScript, and interface assets
├── migrations/             # Database schema migrations
└── deploy/                 # Example service and reverse-proxy configuration
```

## Core data concepts

- **Session:** Name, creation time, visibility/active state, and associated photos.
- **Photo:** Session, generated storage key, upload time, visibility/moderation state, and vote/report counts (or derived counts).
- **Vote:** Photo and persistent client identifier, unique together so the same client cannot vote twice for a photo.
- **TV appearance:** A server-issued identifier for one automatic display of one photo on one paired TV. A TV vote references this identifier, with uniqueness enforced per appearance. This allows another vote on a later automatic appearance while preventing duplicate requests for the same appearance.
- **Report:** Photo, client identifier, time, and review state. Reports should be rate-limited and deduplicated per client and photo.
- **Booth credential:** A revocable credential associated with an installation, used to authorize uploads.
- **Configuration:** The report threshold and slideshow behavior should be configurable by an administrator.

“One vote per client” means one per persistent browser identifier, not one per person. Visitors can use another browser or clear local storage, so this should not be described as identity verification.

### TV vote eligibility

The server creates a new TV appearance identifier when the slideshow advances automatically to a photo. The TV can submit at most one vote for that photo during that appearance. When the slideshow later returns to the same photo automatically, it receives a new appearance identifier and can be upvoted again.

Manual previous/next controls must not create a new vote opportunity. The server should mark manually selected slides as ineligible for TV votes, or preserve the current appearance identifier without issuing a new one. This prevents repeatedly stepping around the slideshow to vote for the same photo again. The TV UI should show when a vote was accepted and when the current slide cannot be voted on.

### TV setup and pairing

On first boot, the Pi connects to venue Wi-Fi through a local setup flow, then opens the stable gallery TV URL. Until an administrator pairs it, the screen displays a setup code. The administrator enters the code in the gallery admin interface and selects the session for that display. The gallery stores the assignment against the paired TV identity; changing the session or revoking the display is an admin action. The same setup code must not act as the long-lived device credential.

## Upload and moderation safeguards

The upload API should authenticate each booth, enforce request and image size limits, validate decoded image content instead of trusting the MIME type, generate its own filenames, and store files outside the web root. Public photo delivery should use controlled identifiers and should not expose filesystem paths. Reports should be rate-limited. Moderators should be able to inspect hidden photos and restore a photo after review.

## Suggested implementation milestones

1. Define upload authentication and how booth session IDs map to gallery sessions.
2. Add the Flask service, PostgreSQL schema, and durable image storage.
3. Implement booth uploads, session listing, and photo browsing.
4. Add TV setup codes, admin pairing, session assignment, and the TV slideshow with automatic refresh.
5. Add browser voting, per-automatic-appearance TV voting, and weighted slideshow rotation.
6. Add reports, threshold-based hiding, and moderator review.
7. Document production deployment, backups, retention, and TV setup.

## Decisions to settle before implementation

- What makes a session “active”: an explicit admin action, booth activity, or both?
- How should a booth authenticate, and should booths be able to create sessions or only upload into assigned sessions?
- How should a Pi initially connect to venue Wi-Fi, and what recovery flow should it show when saved Wi-Fi credentials stop working?
- How long should sessions and original image files be retained?
- Should the service be public, event-password protected, or configurable per session?
- What defaults should control slideshow timing, vote weighting, report threshold, and moderation access?
