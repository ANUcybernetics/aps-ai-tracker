<script lang="ts">
  import {
    forceCenter,
    forceCollide,
    forceLink,
    forceManyBody,
    forceSimulation,
    type SimulationLinkDatum,
    type SimulationNodeDatum,
  } from "d3-force";
  import { select } from "d3-selection";
  import { zoom } from "d3-zoom";
  import { drag } from "d3-drag";
  import { scaleLinear } from "d3-scale";
  import { dataUrl } from "@/lib/paths";
  import type { GraphData, GraphNode } from "@/types/exporter";

  type GNode = GraphNode & SimulationNodeDatum;
  type GLink = SimulationLinkDatum<GNode> & { score: number };

  let container: HTMLDivElement;
  let status = $state<"loading" | "empty" | "ready">("loading");

  $effect(() => {
    let stop = () => {};
    void (async () => {
      const data: GraphData = await (await fetch(dataUrl("similarity.graph.json"))).json();
      if (!data.nodes.length) {
        status = "empty";
        return;
      }
      status = "ready";
      stop = render(data);
    })();
    return () => stop();
  });

  function render(data: GraphData): () => void {
    const width = container.clientWidth || 800;
    const height = 600;
    const nodes: GNode[] = data.nodes.map((n) => ({ ...n }));
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const links: GLink[] = data.edges.map((e) => ({
      source: byId.get(e.a)!,
      target: byId.get(e.b)!,
      score: e.score,
    }));

    // Originality → colour, matching the site-wide language: warm ochre =
    // heavily templated/borrowed, cool teal = bespoke, neutral in between. Mid
    // lightness so nodes stay legible on both the light and dark canvas.
    const colour = scaleLinear<string>()
      .domain([0, 0.5, 1])
      .range(["#c6862f", "#9aa1ab", "#3f8f9c"])
      .clamp(true);

    const svg = select(container)
      .append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img")
      .attr("aria-label", "Force-directed map of statement similarity");

    const root = svg.append("g");

    svg.call(
      zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.3, 6])
        .on("zoom", (event) => root.attr("transform", event.transform)),
    );

    const link = root
      .append("g")
      .attr("stroke", "currentColor")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke-opacity", (d) => 0.1 + (d.score - 0.8) * 1.5)
      .attr("stroke-width", (d) => 0.5 + (d.score - 0.8) * 6);

    const node = root
      .append("g")
      .selectAll<SVGGElement, GNode>("g")
      .data(nodes)
      .join("g")
      .style("cursor", "grab");

    node
      .append("circle")
      .attr("r", 7)
      .attr("fill", (d) => colour(d.originality))
      .attr("stroke", "var(--bg)")
      .attr("stroke-width", 1.5);

    node
      .append("text")
      .text((d) => d.abbr)
      .attr("x", 10)
      .attr("y", 4)
      .attr("font-size", "0.7rem")
      .attr("fill", "currentColor");

    node.append("title").text((d) => `${d.abbr} — ${Math.round(d.originality * 100)}% bespoke`);

    const reduceMotion =
      typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

    function ticked(): void {
      link
        .attr("x1", (d) => (d.source as GNode).x!)
        .attr("y1", (d) => (d.source as GNode).y!)
        .attr("x2", (d) => (d.target as GNode).x!)
        .attr("y2", (d) => (d.target as GNode).y!);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    }

    const sim = forceSimulation(nodes)
      .force(
        "link",
        forceLink<GNode, GLink>(links)
          .id((d) => d.id)
          .distance((d) => 140 * (1 - d.score)),
      )
      .force("charge", forceManyBody().strength(-130))
      .force("center", forceCenter(width / 2, height / 2))
      .force("collide", forceCollide(16))
      .on("tick", ticked);

    // Reduced motion: settle the layout synchronously and paint once, so nodes
    // don't animate into place. Dragging still works (below), just without the
    // springy reflow of the rest of the graph.
    if (reduceMotion) {
      sim.stop();
      for (let i = 0; i < 300; i++) sim.tick();
      ticked();
    }

    node.call(
      drag<SVGGElement, GNode>()
        .on("start", (event, d) => {
          if (!reduceMotion && !event.active) sim.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on("drag", (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
          if (reduceMotion) {
            d.x = event.x;
            d.y = event.y;
            ticked();
          }
        })
        .on("end", (event, d) => {
          if (!reduceMotion && !event.active) sim.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        }),
    );

    return () => {
      sim.stop();
      svg.remove();
    };
  }
</script>

<div class="graph" bind:this={container}>
  {#if status === "loading"}
    <p class="graph__msg muted">Loading similarity map…</p>
  {:else if status === "empty"}
    <p class="graph__msg muted">
      Similarity isn&rsquo;t computed yet (the build had no embedding key). The table below still
      lists each statement&rsquo;s nearest matches once available.
    </p>
  {/if}
</div>

<style>
  .graph {
    position: relative;
    min-block-size: 600px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    overflow: hidden;
  }

  .graph :global(svg) {
    display: block;
    inline-size: 100%;
    block-size: 600px;
    color: var(--muted);
  }

  .graph__msg {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    text-align: center;
    padding: var(--space-6);
    margin: 0;
    max-inline-size: 40rem;
    margin-inline: auto;
  }
</style>
