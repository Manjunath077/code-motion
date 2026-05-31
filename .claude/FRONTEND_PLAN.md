# AlgoAnimate — Frontend Implementation Plan

## Project Understanding

AlgoAnimate's frontend is a React + TypeScript SPA. Users type a natural language prompt, the app submits it to the backend, then polls for completion status. When rendering is done the user can watch the Manim animation video inline, download it, and browse their history of past animations.

### Current State (already scaffolded)
- Vite + React + TypeScript project created
- Default Vite starter template in `src/App.tsx` (not customized)
- `package.json` exists but does NOT yet have: Tailwind, shadcn/ui, Redux Toolkit, RTK Query, React Router

### What Does NOT Exist Yet
- Tailwind CSS and shadcn/ui component library
- Redux Toolkit store and RTK Query API slice
- React Router with page routing
- Any real UI: prompt form, status display, video player, scene history

### Tech Stack (from spec)
- React 18 + TypeScript
- Vite (build tool — already set up)
- Tailwind CSS (styling)
- shadcn/ui (component library built on Radix UI)
- Redux Toolkit + RTK Query (state management + data fetching)
- React Router v6 (routing)

---

## Architecture Overview

```
src/
├── app/
│   ├── store.ts              # Redux store
│   └── hooks.ts              # typed useAppDispatch / useAppSelector
├── features/
│   ├── api/
│   │   └── apiSlice.ts       # RTK Query base API + all endpoints
│   ├── prompt/
│   │   ├── promptSlice.ts    # local UI state for prompt form
│   │   └── PromptPage.tsx    # main prompt submission page
│   └── scenes/
│       ├── scenesSlice.ts    # (optional extra state)
│       ├── SceneHistoryPage.tsx
│       ├── SceneDetailPage.tsx
│       └── components/
│           ├── SceneCard.tsx
│           ├── StatusBadge.tsx
│           └── VideoPlayer.tsx
├── components/
│   ├── Layout.tsx            # shell with nav
│   ├── Navbar.tsx
│   └── ui/                  # shadcn/ui generated components live here
├── types/
│   └── scene.ts              # TypeScript types matching backend schemas
├── lib/
│   └── utils.ts              # cn() helper (shadcn default)
├── pages/
│   └── NotFound.tsx
├── App.tsx                   # Router setup
└── main.tsx                  # Redux Provider + React root
```

### Data Flow

```
User types prompt
      |
      v
PromptPage dispatches RTK Query mutation (POST /api/v1/prompt)
      |
      v
Backend returns { scene_id, status: "queued" } immediately
      |
      v
Frontend starts polling GET /api/v1/scenes/{scene_id} every 3s
      |
      v
Status badge updates: pending → validating → queued → rendering → completed
      |
      v
When completed: VideoPlayer renders with the video_url from the scene
```

---

## Phase 1 — Project Setup & Tooling

**Goal:** Replace the Vite starter template with a properly configured project that has Tailwind, shadcn/ui, Redux, and routing ready to use.

### Tasks

1. **Install and configure Tailwind CSS**:
   ```bash
   npm install -D tailwindcss postcss autoprefixer
   npx tailwindcss init -p
   ```
   Update `tailwind.config.js`:
   ```js
   content: ["./index.html", "./src/**/*.{ts,tsx}"]
   ```
   Add Tailwind directives to `src/index.css`:
   ```css
   @tailwind base;
   @tailwind components;
   @tailwind utilities;
   ```

2. **Install and initialize shadcn/ui**:
   ```bash
   npx shadcn-ui@latest init
   ```
   Choose: TypeScript, Tailwind, `src/components/ui` for component dir, `src/lib/utils.ts` for utils.
   Add initial components used across the app:
   ```bash
   npx shadcn-ui@latest add button input textarea badge card toast dialog
   ```

3. **Install Redux Toolkit + RTK Query**:
   ```bash
   npm install @reduxjs/toolkit react-redux
   ```

4. **Install React Router**:
   ```bash
   npm install react-router-dom
   ```

5. **Install additional utilities**:
   ```bash
   npm install clsx tailwind-merge     # cn() helper for conditional classes
   npm install lucide-react            # icons
   ```

6. **Create `src/app/store.ts`**:
   ```typescript
   import { configureStore } from "@reduxjs/toolkit";
   import { apiSlice } from "../features/api/apiSlice";

   export const store = configureStore({
     reducer: {
       [apiSlice.reducerPath]: apiSlice.reducer,
     },
     middleware: (getDefaultMiddleware) =>
       getDefaultMiddleware().concat(apiSlice.middleware),
   });

   export type RootState = ReturnType<typeof store.getState>;
   export type AppDispatch = typeof store.dispatch;
   ```

7. **Create `src/app/hooks.ts`** — typed Redux hooks:
   ```typescript
   import { useDispatch, useSelector, TypedUseSelectorHook } from "react-redux";
   import type { RootState, AppDispatch } from "./store";

   export const useAppDispatch = () => useDispatch<AppDispatch>();
   export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;
   ```

8. **Wrap app in providers in `src/main.tsx`**:
   ```typescript
   import { Provider } from "react-redux";
   import { store } from "./app/store";
   import { BrowserRouter } from "react-router-dom";

   ReactDOM.createRoot(document.getElementById("root")!).render(
     <React.StrictMode>
       <Provider store={store}>
         <BrowserRouter>
           <App />
         </BrowserRouter>
       </Provider>
     </React.StrictMode>
   );
   ```

9. **Set up `.env` for local API base URL**:
   ```
   # frontend/.env.local
   VITE_API_BASE_URL=http://localhost:8000
   ```

**Milestone:** `npm run dev` launches with no errors. A test Tailwind class (e.g. `bg-blue-500`) renders correctly. shadcn `Button` renders.

---

## Phase 2 — Type Definitions & RTK Query API Slice

**Goal:** Establish the contract between frontend and backend before building any UI. All API calls go through RTK Query — no direct `fetch`.

### Tasks

1. **`src/types/scene.ts`** — mirror backend Pydantic schemas exactly:
   ```typescript
   export type SceneStatus =
     | "pending"
     | "validating"
     | "queued"
     | "rendering"
     | "completed"
     | "failed";

   export interface Scene {
     id: string;
     prompt: string;
     generated_script: string | null;
     status: SceneStatus;
     video_url: string | null;
     error_message: string | null;
     created_at: string;
     updated_at: string;
   }

   export interface SceneListResponse {
     scenes: Scene[];
     total: number;
   }

   export interface PromptRequest {
     prompt: string;
   }

   export interface PromptResponse {
     scene_id: string;
     status: SceneStatus;
   }
   ```

2. **`src/features/api/apiSlice.ts`** — RTK Query base API with all endpoints:
   ```typescript
   import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";
   import type { Scene, SceneListResponse, PromptRequest, PromptResponse } from "../../types/scene";

   export const apiSlice = createApi({
     reducerPath: "api",
     baseQuery: fetchBaseQuery({
       baseUrl: import.meta.env.VITE_API_BASE_URL + "/api/v1",
     }),
     tagTypes: ["Scene"],
     endpoints: (builder) => ({
       submitPrompt: builder.mutation<PromptResponse, PromptRequest>({
         query: (body) => ({ url: "/prompt", method: "POST", body }),
         invalidatesTags: ["Scene"],
       }),
       getScene: builder.query<Scene, string>({
         query: (id) => `/scenes/${id}`,
         providesTags: (_, __, id) => [{ type: "Scene", id }],
       }),
       listScenes: builder.query<SceneListResponse, { skip?: number; limit?: number }>({
         query: ({ skip = 0, limit = 20 } = {}) =>
           `/scenes?skip=${skip}&limit=${limit}`,
         providesTags: ["Scene"],
       }),
       regenerateScene: builder.mutation<PromptResponse, string>({
         query: (id) => ({ url: `/scenes/${id}/regenerate`, method: "POST" }),
         invalidatesTags: (_, __, id) => [{ type: "Scene", id }, "Scene"],
       }),
       deleteScene: builder.mutation<void, string>({
         query: (id) => ({ url: `/scenes/${id}`, method: "DELETE" }),
         invalidatesTags: ["Scene"],
       }),
     }),
   });

   export const {
     useSubmitPromptMutation,
     useGetSceneQuery,
     useListScenesQuery,
     useRegenerateSceneMutation,
     useDeleteSceneMutation,
   } = apiSlice;
   ```

3. **Export hooks** from `src/features/api/index.ts` for cleaner imports throughout the app.

**Milestone:** TypeScript compiles with no errors. All hooks are importable. (No UI yet — verify by checking TS output.)

---

## Phase 3 — Layout & Routing Shell

**Goal:** App has a consistent shell (navbar + content area) and navigation between pages.

### Tasks

1. **`src/components/Navbar.tsx`** — sticky top nav:
   - Logo / app name "AlgoAnimate" on the left
   - Nav links: "Generate" (→ `/`) and "History" (→ `/scenes`)
   - Uses `NavLink` from React Router for active state styling

2. **`src/components/Layout.tsx`** — wraps all pages:
   ```tsx
   export function Layout({ children }: { children: React.ReactNode }) {
     return (
       <div className="min-h-screen bg-background text-foreground">
         <Navbar />
         <main className="container mx-auto px-4 py-8 max-w-5xl">
           {children}
         </main>
       </div>
     );
   }
   ```

3. **`src/App.tsx`** — set up routes:
   ```tsx
   import { Routes, Route } from "react-router-dom";
   import { Layout } from "./components/Layout";
   import { PromptPage } from "./features/prompt/PromptPage";
   import { SceneHistoryPage } from "./features/scenes/SceneHistoryPage";
   import { SceneDetailPage } from "./features/scenes/SceneDetailPage";
   import { NotFound } from "./pages/NotFound";

   export default function App() {
     return (
       <Layout>
         <Routes>
           <Route path="/" element={<PromptPage />} />
           <Route path="/scenes" element={<SceneHistoryPage />} />
           <Route path="/scenes/:id" element={<SceneDetailPage />} />
           <Route path="*" element={<NotFound />} />
         </Routes>
       </Layout>
     );
   }
   ```

4. **Dark theme** — configure shadcn/ui with dark mode. Add `class="dark"` to `<html>` tag (or implement a toggle). The animation platform aesthetic suits a dark background.

5. **Color scheme** — in `tailwind.config.js`, extend with brand colors:
   ```js
   colors: {
     brand: { DEFAULT: "#6366f1", dark: "#4f46e5" }  // indigo
   }
   ```

**Milestone:** App loads, navbar appears, clicking "Generate" and "History" navigates between pages (pages can render empty placeholders at this point).

---

## Phase 4 — Prompt Submission Page

**Goal:** The core user interaction — type a prompt, submit it, see immediate feedback.

### Tasks

1. **`src/features/prompt/PromptPage.tsx`** — the main page:

   **Layout:**
   - Page title + subtitle ("Convert any algorithm description into a Manim animation")
   - Large textarea for prompt input (min 4 rows)
   - Character counter (e.g. "142 / 2000")
   - "Generate Animation" button with loading spinner while submitting
   - Submission tips / example prompts section below the form

   **Behavior:**
   - On submit: call `useSubmitPromptMutation`
   - On success: store returned `scene_id` in local state, transition to status polling view
   - On error: show error toast with the error message from backend

2. **Inline status tracker component** — shown after submission on the same page (replaces the form while polling):
   ```
   [●] Generating script...    ← validating
   [●] Queued for rendering... ← queued
   [●] Rendering animation...  ← rendering
   [✓] Done!                   ← completed → show video
   [✗] Failed: <error message> ← failed
   ```
   Each step is a row in a vertical stepper UI (use shadcn `Progress` or custom step indicators).

3. **RTK Query polling** — use `useGetSceneQuery` with `pollingInterval`:
   ```typescript
   const { data: scene } = useGetSceneQuery(sceneId, {
     pollingInterval: sceneId && !isDone(scene?.status) ? 3000 : 0,
     skip: !sceneId,
   });

   function isDone(status?: SceneStatus) {
     return status === "completed" || status === "failed";
   }
   ```
   Stop polling once status is `completed` or `failed`.

4. **Example prompt suggestions** — below the textarea, show 3-4 clickable chips:
   - "Visualize bubble sort step by step"
   - "Show binary search tree insertion"
   - "Animate Dijkstra's shortest path"
   - "Demonstrate merge sort with colored bars"
   Clicking a chip fills the textarea.

5. **Form validation** — disable submit if:
   - Prompt is empty
   - Prompt exceeds 2000 characters
   - A submission is already in progress

**Milestone:** Typing a prompt and clicking submit hits the backend, returns `scene_id`, and the status stepper updates as the backend processes the job.

---

## Phase 5 — Video Player & Inline Result

**Goal:** When a scene reaches `completed`, display the rendered video directly on the page.

### Tasks

1. **`src/features/scenes/components/VideoPlayer.tsx`**:
   ```tsx
   interface Props {
     videoUrl: string;    // full URL: VITE_API_BASE_URL + scene.video_url
     sceneId: string;
   }

   export function VideoPlayer({ videoUrl, sceneId }: Props) {
     return (
       <div className="rounded-xl overflow-hidden border border-border bg-black aspect-video">
         <video
           src={videoUrl}
           controls
           autoPlay
           loop
           className="w-full h-full"
         />
       </div>
     );
   }
   ```

2. **Download button** — below the player:
   ```tsx
   <a
     href={videoUrl}
     download={`algoanimate-${sceneId}.mp4`}
     className="..."
   >
     <Download className="w-4 h-4 mr-2" /> Download MP4
   </a>
   ```

3. **Script preview** — collapsible section below the video (use shadcn `Collapsible` or `Accordion`):
   - Shows the generated Manim Python script
   - Syntax highlighted (use a lightweight library like `prism-react-renderer` or just a `<pre>` with monospace font)
   - Copy-to-clipboard button

4. **Show inline on PromptPage** — after `status === "completed"`, show `VideoPlayer` below the status stepper on the prompt page. The user never navigates away just to see their video.

5. **Error display** — if `status === "failed"`, show the `error_message` in a destructive-styled alert box with a "Try Again" button that resets the form.

**Milestone:** Submitting a prompt that completes renders the video inline on the page with working playback and download.

---

## Phase 6 — Scene History Page

**Goal:** Users can browse all past animations, with status, timestamp, and quick actions.

### Tasks

1. **`src/features/scenes/SceneHistoryPage.tsx`** — page layout:
   - Page title "Your Animations"
   - Grid of `SceneCard` components (2 columns on desktop, 1 on mobile)
   - Empty state when no scenes exist
   - Pagination controls (Previous / Next) with skip/limit

2. **`src/features/scenes/components/SceneCard.tsx`**:
   ```
   ┌─────────────────────────────────────┐
   │  [Video thumbnail or placeholder]   │
   │                                     │
   │  "Animate bubble sort"              │  ← truncated prompt
   │  ● completed      2 hours ago       │  ← StatusBadge + relative time
   │                                     │
   │  [View] [Regenerate] [Delete]       │
   └─────────────────────────────────────┘
   ```
   - Clicking "View" navigates to `SceneDetailPage`
   - Video thumbnail: if `status === "completed"`, render a `<video>` with `poster` attribute or a static frame; otherwise show a placeholder with the status icon

3. **`src/features/scenes/components/StatusBadge.tsx`** — colored badge for each status:
   - `pending` → gray
   - `validating` → blue
   - `queued` → yellow
   - `rendering` → orange with spinner
   - `completed` → green
   - `failed` → red

4. **Relative timestamps** — install `date-fns`:
   ```bash
   npm install date-fns
   ```
   Use `formatDistanceToNow(new Date(scene.created_at))` → "3 hours ago".

5. **Delete confirmation** — clicking "Delete" opens a shadcn `AlertDialog` to confirm before calling `useDeleteSceneMutation`.

6. **Polling in-progress scenes** — for any scene on the history page that is NOT `completed`/`failed`, poll every 5s to update its status card in real time.

7. **RTK Query cache** — `listScenes` is auto-invalidated when a new prompt is submitted (via `invalidatesTags: ["Scene"]` in the mutation).

**Milestone:** History page shows all past scenes with correct status badges, relative times, and delete confirmation.

---

## Phase 7 — Scene Detail Page

**Goal:** A dedicated page for a single scene with full details — video, script, prompt, regeneration.

### Tasks

1. **`src/features/scenes/SceneDetailPage.tsx`** — accessed at `/scenes/:id`:
   - Pull `:id` from URL with `useParams()`
   - Fetch with `useGetSceneQuery(id)` (polls if not done)
   - Layout:
     - Prompt text at top (in a styled blockquote)
     - Status badge + timestamp
     - `VideoPlayer` (if completed)
     - Script preview accordion
     - Action buttons: "Regenerate" | "Delete" | "Back to History"

2. **Regenerate flow**:
   - Click "Regenerate" → call `useRegenerateSceneMutation(id)`
   - On success: scene status resets; polling resumes automatically (RTK Query re-fetches because tag is invalidated)
   - Show toast: "Regeneration queued..."

3. **Loading state** — while `getScene` is loading initially, show a full-page skeleton (`SceneDetailSkeleton`) matching the layout.

4. **404 state** — if backend returns 404, show a "Scene not found" message with a "Back to History" link.

**Milestone:** Navigating to `/scenes/:id` shows the full scene. Regenerate resets the status and re-polls. Delete navigates back to history.

---

## Phase 8 — UI Polish & Responsiveness

**Goal:** Production-quality look and feel. Dark theme, responsive, accessible.

### Tasks

1. **Dark theme finalization**:
   - Ensure all shadcn components use CSS variables (`bg-background`, `text-foreground`) which respect dark mode
   - Gradient hero background on `PromptPage` (subtle dark gradient or animated gradient)
   - Code blocks use a dark monospace style

2. **Loading skeletons** — replace all "Loading..." text with shadcn `Skeleton` components:
   - `SceneCardSkeleton` — placeholder for history cards while loading
   - `SceneDetailSkeleton` — placeholder for detail page
   - Use CSS shimmer animation

3. **Toast notifications** — wire up shadcn `Toaster` in `Layout.tsx`:
   - "Animation queued successfully" on submit
   - "Scene deleted" on delete
   - "Regeneration started" on regenerate
   - "Error: ..." on failures

4. **Responsive layout**:
   - Mobile: single-column layout, full-width textarea, bottom-fixed action bar
   - Tablet: 2-column history grid
   - Desktop: centered container, max-width 1024px

5. **Accessibility**:
   - All interactive elements have `aria-label`
   - Status changes announced via `aria-live="polite"` region
   - Video player keyboard controls work

6. **Favicon and metadata** — update `index.html` `<title>` and `<meta>` description.

7. **Empty states** — custom illustrated empty state for history page ("No animations yet. Generate your first one!").

8. **Micro-animations** — subtle Tailwind transition on cards (`hover:scale-[1.02]`, `transition-all duration-200`).

**Milestone:** App looks polished on mobile and desktop. All transitions are smooth. Toasts appear for every user action.

---

## Phase 9 — Error Handling & Edge Cases

**Goal:** Handle all failure modes gracefully so the user is never left confused.

### Tasks

1. **Global error boundary** — wrap `<App>` in a React `ErrorBoundary` that shows a friendly error page instead of a blank white screen.

2. **Network error handling in RTK Query** — add a custom `baseQuery` wrapper that catches 429 (rate limit) and 5xx errors and shows specific toast messages:
   - 429: "Too many requests. Please wait a minute before trying again."
   - 503: "Server is temporarily unavailable. Please try again."
   - 422: Show the backend's validation error message directly

3. **Polling timeout** — if a scene stays in a non-terminal state for more than 5 minutes, stop polling and show: "This is taking longer than expected. [Refresh status]"

4. **API base URL misconfiguration** — if `VITE_API_BASE_URL` is not set, show a dev-only warning in the console and on-screen.

5. **Video load error** — if the `<video>` element fires `onError`, show: "Video failed to load. Try downloading it directly." with a fallback download link.

**Milestone:** Every failure mode shows a meaningful message. No blank screens or unhandled promise rejections in the browser console.

---

## Implementation Order Summary

| Phase | Focus | Key Output |
|-------|-------|-----------|
| 1 | Tooling setup | Tailwind, shadcn/ui, Redux, Router configured |
| 2 | Types + RTK Query | API slice with all endpoints, TypeScript types |
| 3 | Layout + routing | Nav, shell, 4 routes defined |
| 4 | Prompt page | Form, submit, inline status stepper with polling |
| 5 | Video player | Inline playback, download, script preview |
| 6 | Scene history | Cards, StatusBadge, pagination, delete |
| 7 | Scene detail | Dedicated page, regenerate, 404 handling |
| 8 | UI polish | Dark theme, skeletons, toasts, responsive |
| 9 | Error handling | Error boundary, network errors, edge cases |

---

## Key File Map (End State)

```
frontend/src/
├── app/
│   ├── store.ts                    # Redux store
│   └── hooks.ts                    # Typed dispatch/selector hooks
├── features/
│   ├── api/
│   │   └── apiSlice.ts             # RTK Query: all 5 endpoints
│   ├── prompt/
│   │   └── PromptPage.tsx          # Prompt form + status stepper + inline video
│   └── scenes/
│       ├── SceneHistoryPage.tsx    # Paginated scene list
│       ├── SceneDetailPage.tsx     # Single scene view + regenerate
│       └── components/
│           ├── SceneCard.tsx       # Card with thumbnail, status, actions
│           ├── SceneCardSkeleton.tsx
│           ├── StatusBadge.tsx     # Color-coded status badge
│           └── VideoPlayer.tsx     # HTML5 video + download button
├── components/
│   ├── Layout.tsx                  # Shell with Navbar + Toaster
│   ├── Navbar.tsx                  # Logo + nav links
│   └── ui/                        # shadcn/ui generated components
├── types/
│   └── scene.ts                   # Scene, SceneStatus, PromptRequest/Response
├── lib/
│   └── utils.ts                   # cn() helper (Tailwind class merging)
├── pages/
│   └── NotFound.tsx
├── App.tsx                         # Route definitions
├── main.tsx                        # Provider + BrowserRouter + ReactDOM
└── index.css                       # Tailwind directives + global styles
```

---

## Environment Variables

```bash
# frontend/.env.local
VITE_API_BASE_URL=http://localhost:8000

# frontend/.env.production
VITE_API_BASE_URL=https://your-production-domain.com
```

All API calls construct the URL as: `${import.meta.env.VITE_API_BASE_URL}/api/v1/...`

---

## Dependency Install (Complete List)

```bash
# Core setup
npm install -D tailwindcss postcss autoprefixer
npm install @reduxjs/toolkit react-redux
npm install react-router-dom

# shadcn/ui (run init first, then add components)
npx shadcn-ui@latest init
npx shadcn-ui@latest add button input textarea badge card toast dialog alert-dialog accordion collapsible progress skeleton

# Icons and utilities
npm install lucide-react
npm install clsx tailwind-merge
npm install date-fns

# Optional: syntax highlighting for script preview
npm install prism-react-renderer
```
