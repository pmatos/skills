# Visual Companion Guide

Browser-based visual brainstorming companion for showing mockups, diagrams, and options.

> **Note:** The visual companion server scripts are not bundled with this skill. If you want to use the visual companion, you'll need a local HTTP server that can serve HTML files. The guide below describes the interaction pattern — adapt the server setup to your environment.

## When to Use

Decide per-question, not per-session. The test: **would the user understand this better by seeing it than reading it?**

**Use the browser** when the content itself is visual:

- **UI mockups** — wireframes, layouts, navigation structures, component designs
- **Architecture diagrams** — system components, data flow, relationship maps
- **Side-by-side visual comparisons** — comparing two layouts, two color schemes, two design directions
- **Design polish** — when the question is about look and feel, spacing, visual hierarchy
- **Spatial relationships** — state machines, flowcharts, entity relationships rendered as diagrams

**Use the terminal** when the content is text or tabular:

- **Requirements and scope questions** — "what does X mean?", "which features are in scope?"
- **Conceptual A/B/C choices** — picking between approaches described in words
- **Tradeoff lists** — pros/cons, comparison tables
- **Technical decisions** — API design, data modeling, architectural approach selection
- **Clarifying questions** — anything where the answer is words, not a visual preference

A question *about* a UI topic is not automatically a visual question. "What kind of wizard do you want?" is conceptual — use the terminal. "Which of these wizard layouts feels right?" is visual — use the browser.

## How It Works

The general pattern: a local server watches a directory for HTML files and serves the newest one to the browser. You write HTML content to a content directory, the user sees it in their browser and can click to select options.

## The Loop

1. **Write HTML** to a file in the content directory:
   - Use semantic filenames: `platform.html`, `visual-style.html`, `layout.html`
   - **Never reuse filenames** — each screen gets a fresh file
   - Use Write tool — **never use cat/heredoc**

2. **Tell user what to expect and end your turn:**
   - Remind them of the URL (every step, not just first)
   - Give a brief text summary of what's on screen (e.g., "Showing 3 layout options for the homepage")
   - Ask them to respond in the terminal: "Take a look and let me know what you think."

3. **On your next turn** — after the user responds in the terminal:
   - Read any event/interaction files if available
   - Merge with the user's terminal text to get the full picture

4. **Iterate or advance** — if feedback changes current screen, write a new file (e.g., `layout-v2.html`). Only move to the next question when the current step is validated.

5. **Unload when returning to terminal** — when the next step doesn't need the browser, push a waiting screen:

   ```html
   <div style="display:flex;align-items:center;justify-content:center;min-height:60vh">
     <p style="color:#888;font-size:1.2em;">Continuing in terminal...</p>
   </div>
   ```

6. Repeat until done.

## Writing Content

Write just the content HTML. Keep it simple and focused on the question being asked.

**Minimal example:**

```html
<h2>Which layout works better?</h2>
<p style="color:#888;">Consider readability and visual hierarchy</p>

<div style="display:flex;gap:2rem;margin-top:2rem;">
  <div style="flex:1;border:1px solid #333;border-radius:8px;padding:1.5rem;">
    <h3>A: Single Column</h3>
    <p>Clean, focused reading experience</p>
  </div>
  <div style="flex:1;border:1px solid #333;border-radius:8px;padding:1.5rem;">
    <h3>B: Two Column</h3>
    <p>Sidebar navigation with main content</p>
  </div>
</div>
```

## Design Tips

- **Scale fidelity to the question** — wireframes for layout, polish for polish questions
- **Explain the question on each page** — "Which layout feels more professional?" not just "Pick one"
- **Iterate before advancing** — if feedback changes current screen, write a new version
- **2-4 options max** per screen
- **Use real content when it matters** — placeholder content obscures design issues
- **Keep mockups simple** — focus on layout and structure, not pixel-perfect design

## File Naming

- Use semantic names: `platform.html`, `visual-style.html`, `layout.html`
- Never reuse filenames — each screen must be a new file
- For iterations: append version suffix like `layout-v2.html`, `layout-v3.html`
