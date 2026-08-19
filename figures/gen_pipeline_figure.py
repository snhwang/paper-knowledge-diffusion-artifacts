"""
gen_pipeline_figure.py — Generate the BEAR pipeline schematic (Figure 2 of the manuscript)

Output: bear_pipeline.pdf and bear_pipeline.png in the same directory.

Usage:
    python figures/gen_pipeline_figure.py
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from pathlib import Path

HERE = Path(__file__).parent

# ── Colors ────────────────────────────────────────────────────────────────
TEAL      = '#01696F'
TEAL_LT   = '#D4ECEC'
ORANGE    = '#964219'
ORANGE_LT = '#F5E6DA'
BLUE      = '#006494'
BLUE_LT   = '#D4E8F0'
GRAY      = '#F7F6F2'
BORDER    = '#D4D1CA'
TEXT      = '#28251D'
MUTED     = '#555550'

# ── Font sizes
# Figure is ~14in wide; included in paper at ~7in (ACM TiiS textwidth)
# → scale factor ~0.5, so source fonts need to be ~2x target print size
# Target: 10pt body, 11pt headings → source: BASE=16, HEAD=18, SUB=13
BASE = 16
SUB  = 13
HEAD = 18

# ── Column layout ─────────────────────────────────────────────────────────
LX = 0.2    # left column x
LW = 2.6    # left column width
SX = 3.3    # pipeline x
SW = 5.6    # pipeline width
RX = 9.8    # right column x
RW = 2.9    # right column width


def rbox(ax, x, y, w, h, fc, ec, text, fs=BASE, bold=False,
         subtext=None, sfs=SUB, radius=0.2):
    """Draw a rounded rectangle with optional subtitle."""
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        fc=fc, ec=ec, lw=1.6, zorder=3,
    ))
    ty = y + h / 2 + (0.16 if subtext else 0)
    ax.text(x + w / 2, ty, text,
            ha='center', va='center', fontsize=fs, color=TEXT,
            fontweight='bold' if bold else 'normal', zorder=4, linespacing=1.35)
    if subtext:
        ax.text(x + w / 2, y + h / 2 - 0.25, subtext,
                ha='center', va='center', fontsize=sfs, color=MUTED, zorder=4)


def arrow(ax, x0, y0, x1, y1, color=TEAL, lw=2.0, dashed=False,
          mutation_scale=16):
    """Draw a single straight arrow."""
    ax.annotate('', xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(
                    arrowstyle='->',
                    color=color, lw=lw,
                    linestyle='--' if dashed else '-',
                    mutation_scale=mutation_scale,
                ), zorder=5)


def polyarrow(ax, pts, color=TEAL, lw=2.0, dashed=False):
    """Draw a multi-segment arrow through waypoints, arrowhead on final segment."""
    ls = '--' if dashed else '-'
    for i in range(len(pts) - 2):
        ax.plot(
            [pts[i][0], pts[i + 1][0]],
            [pts[i][1], pts[i + 1][1]],
            color=color, lw=lw, linestyle=ls, zorder=5, solid_capstyle='round',
        )
    ax.annotate('', xy=pts[-1], xytext=pts[-2],
                arrowprops=dict(
                    arrowstyle='->',
                    color=color, lw=lw,
                    linestyle=ls, mutation_scale=16,
                ), zorder=5)


def make_figure():
    fig, ax = plt.subplots(figsize=(14, 9.5))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 9.5)
    ax.axis('off')

    # ── Left column: inputs ───────────────────────────────────────────────
    rbox(ax, LX, 6.6, LW, 1.1, BLUE_LT, BLUE,
         'Query + Context', bold=True)
    rbox(ax, LX, 4.8, LW, 1.5, ORANGE_LT, ORANGE,
         'Behavioral\nInstruction Corpus', bold=True,
         subtext='YAML · typed · scoped')
    rbox(ax, LX, 2.8, LW, 1.5, ORANGE_LT, ORANGE,
         'Knowledge\nStore', bold=True,
         subtext='ChromaDB · per-hat')

    # ── Center: 7-step pipeline ───────────────────────────────────────────
    steps = [
        '①  Embed query + context metadata',
        '②  Retrieve 3k candidates  (vector search)',
        '③  Dual-path scope filter\n      (sim ≥ θ  or  scope match)',
        '④  Priority score:  (1−α)·sim + α·priority/100',
        '⑤  Inject mandatory safety instructions',
        '⑥  Resolve conflicts / requirements / supersedes',
        '⑦  Compose top-k → structured system prompt',
    ]
    step_heights = [0.60, 0.60, 0.90, 0.60, 0.60, 0.60, 0.60]
    gap   = 0.20
    top_y = 8.45

    # Each step box's bottom-left y. Box i sits below box i-1 with `gap`
    # between them; the next box's top edge is `prev_bottom - gap`, and its
    # bottom-left is that minus its own height. Using the previous step's
    # height instead would cause taller boxes (step ③) to overlap upward.
    ys = []
    for i, h_i in enumerate(step_heights):
        if i == 0:
            ys.append(top_y)
        else:
            ys.append(ys[i - 1] - gap - h_i)

    frame_top    = top_y + step_heights[0] + 0.35
    frame_bottom = ys[-1] - 0.35
    ax.add_patch(FancyBboxPatch(
        (SX - 0.2, frame_bottom), SW + 0.4, frame_top - frame_bottom,
        boxstyle="round,pad=0,rounding_size=0.25",
        fc=GRAY, ec=BORDER, lw=1.5, zorder=1,
    ))
    ax.text(SX + SW / 2, frame_top + 0.15, 'BEAR Retrieval Pipeline',
            ha='center', va='bottom', fontsize=HEAD, fontweight='bold',
            color=TEAL, zorder=4)

    for i, (label, y, h_i) in enumerate(zip(steps, ys, step_heights)):
        rbox(ax, SX, y, SW, h_i, TEAL_LT, TEAL, label, radius=0.14)
        if i < len(steps) - 1:
            # short inter-step arrow: head sized to stay proportional to
            # the short connector while still being clearly visible
            arrow(ax, SX + SW / 2, y,
                  SX + SW / 2, ys[i + 1] + step_heights[i + 1],
                  mutation_scale=14)

    # ── Right column: outputs ─────────────────────────────────────────────
    rbox(ax, RX, 5.5, RW, 1.4, ORANGE_LT, ORANGE,
         'Knowledge\nRAG Chunks', bold=True, subtext='per-hat scoped')
    rbox(ax, RX, 3.5, RW, 1.4, TEAL_LT, TEAL,
         'System Prompt', bold=True, subtext='O(k+m) tokens')
    rbox(ax, RX, 1.8, RW, 1.3, BLUE_LT, BLUE,
         'LLM Response', bold=True)

    # ── Bottom: cross-hat cognitive filter ────────────────────────────────
    rbox(ax, LX, 0.2, 13.6, 1.1, TEAL_LT, TEAL,
         'Cross-Hat Cognitive Filter', bold=True,
         subtext=('novel (dist ≥ d_min) → store in receiving hat'
                  '     ·     redundant (dist < d_min) → skip'))

    # ── Arrows ────────────────────────────────────────────────────────────
    # Query → step 1
    arrow(ax, LX + LW, 7.15, SX, ys[0] + step_heights[0] / 2)

    # Behavioral Instruction Corpus → step 2 (straight horizontal)
    arrow(ax, LX + LW, 5.55, SX, ys[1] + step_heights[1] / 2)

    # Knowledge Store → Knowledge RAG Chunks
    # Route: down to gap between cognitive filter (top y=1.3) and LLM
    # Response (bottom y=1.8), across the bottom, up the far right (clear
    # of the right-column boxes), and into the right edge of Knowledge
    # RAG Chunks. Avoids crossing System Prompt and LLM Response.
    ks_cy   = 2.8 + 1.5 / 2          # kstore vertical center
    krag_cy = 5.5 + 1.4 / 2          # krag vertical center
    bottom_gap_y = 1.55              # midway between filter top and LR bottom
    far_right_x  = RX + RW + 0.3     # 13.0, just right of right column
    polyarrow(ax, [
        (LX + LW,    ks_cy),
        (LX + LW,    bottom_gap_y),
        (far_right_x, bottom_gap_y),
        (far_right_x, krag_cy),
        (RX + RW,    krag_cy),
    ], color=ORANGE)

    # Step 7 → system prompt
    step7_cy = ys[-1] + step_heights[-1] / 2
    arrow(ax, SX + SW, step7_cy, RX, step7_cy)

    # Knowledge RAG → system prompt
    arrow(ax, RX + RW / 2, 5.5, RX + RW / 2, 4.9)

    # System prompt → response
    arrow(ax, RX + RW / 2, 3.5, RX + RW / 2, 3.1)

    # Response → diffusion bar
    arrow(ax, RX + RW / 2, 1.8, RX + RW / 2, 1.3)

    # Diffusion → knowledge store bottom edge
    arrow(ax, 1.5, 1.3, 1.5, 2.8)
    ax.text(1.05, 2.05, 'store', fontsize=BASE, color=TEAL,
            ha='center', va='center', rotation=90, fontweight='bold')

    # Experiential memory feedback (dashed): runtime LLM responses are
    # distilled into new typed instructions and added to the Behavioral
    # Instruction Corpus. Routes from LLM Response right edge → up the
    # far right (right of orange line) → over the top of the pipeline
    # frame → down to Behavioral Instruction Corpus right edge.
    lr_cy     = 1.8 + 1.3 / 2        # LLM Response vertical center, 2.45
    bic_cy    = 4.8 + 1.5 / 2        # BIC vertical center, 5.55
    far_far_x = far_right_x + 0.5    # 13.5, right of the orange line
    over_top_y = 9.45                # just above pipeline frame top (9.4)
    side_bic_x = LX + LW + 0.2       # 3.0, between BIC right edge and pipeline left
    polyarrow(ax, [
        (RX + RW,    lr_cy),
        (far_far_x,  lr_cy),
        (far_far_x,  over_top_y),
        (side_bic_x, over_top_y),
        (side_bic_x, bic_cy),
        (LX + LW,    bic_cy),
    ], color=MUTED, dashed=True, lw=1.6)
    ax.text(far_far_x + 0.25, 6.0, 'experiential\nmemory', fontsize=SUB,
            color=MUTED, ha='center', va='center', rotation=90,
            fontstyle='italic')

    plt.tight_layout(pad=0.2)
    plt.savefig(HERE / 'bear_pipeline.pdf', bbox_inches='tight')
    plt.savefig(HERE / 'bear_pipeline.png', bbox_inches='tight', dpi=180)
    print(f"Saved to {HERE}/bear_pipeline.pdf")


if __name__ == '__main__':
    make_figure()
