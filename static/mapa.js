(() => {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.getElementById("mapa-jogadores");
  const grid = document.getElementById("mapa-grade");
  const pins = document.getElementById("mapa-pinos");
  const status = document.getElementById("mapa-status");
  const selected = document.getElementById("jogador-selecionado");
  const timestamp = document.getElementById("mapa-horario");
  if (!svg || !grid || !pins || !status || !selected || !timestamp) return;

  const width = 1000;
  const height = 500;
  const margin = 52;

  function element(tag, attributes = {}) {
    const node = document.createElementNS(ns, tag);
    for (const [name, value] of Object.entries(attributes)) {
      node.setAttribute(name, String(value));
    }
    return node;
  }

  function drawGrid(minX, maxX, minY, maxY) {
    grid.replaceChildren();
    for (let index = 0; index <= 5; index += 1) {
      const x = margin + ((width - margin * 2) * index) / 5;
      const y = margin + ((height - margin * 2) * index) / 5;
      grid.append(element("line", { x1: x, y1: margin, x2: x, y2: height - margin, class: "mapa-grade" }));
      grid.append(element("line", { x1: margin, y1: y, x2: width - margin, y2: y, class: "mapa-grade" }));

      const valorX = minX + ((maxX - minX) * index) / 5;
      const valorY = maxY - ((maxY - minY) * index) / 5;
      const labelX = element("text", { x, y: height - 18, "text-anchor": "middle", class: "mapa-eixo" });
      labelX.textContent = Math.round(valorX).toLocaleString("pt-BR");
      grid.append(labelX);
      const labelY = element("text", { x: 8, y: y + 4, class: "mapa-eixo" });
      labelY.textContent = Math.round(valorY).toLocaleString("pt-BR");
      grid.append(labelY);
    }
  }

  function limits(values) {
    const min = Math.min(...values);
    const max = Math.max(...values);
    const padding = Math.max((max - min) * 0.15, 5000);
    return [min - padding, max + padding];
  }

  async function atualizar() {
    try {
      const resposta = await fetch("/api/mapa/jogadores", {
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const dados = await resposta.json();
      if (!resposta.ok) throw new Error(dados.erro || "Falha ao consultar o servidor.");

      const jogadores = dados.jogadores || [];
      pins.replaceChildren();
      if (jogadores.length === 0) {
        drawGrid(-5000, 5000, -5000, 5000);
        status.textContent = "Nenhum jogador conectado com posição disponível.";
        selected.textContent = "Os pontos aparecem enquanto os jogadores estão online.";
      } else {
        const [minX, maxX] = limits(jogadores.map((jogador) => jogador.x));
        const [minY, maxY] = limits(jogadores.map((jogador) => jogador.y));
        drawGrid(minX, maxX, minY, maxY);
        status.textContent = `${jogadores.length} explorador(es) online`;
        for (const jogador of jogadores) {
          const x = margin + ((jogador.x - minX) / (maxX - minX)) * (width - margin * 2);
          const y = height - margin - ((jogador.y - minY) / (maxY - minY)) * (height - margin * 2);
          const grupo = element("g", { role: "button", tabindex: "0", "aria-label": jogador.nome });
          const pin = element("circle", { cx: x, cy: y, r: 9, class: "pino-jogador" });
          const nome = element("text", { x: x + 12, y: y - 10, class: "nome-jogador" });
          nome.textContent = jogador.nome;
          grupo.append(pin, nome);
          const mostrar = () => {
            const nivel = jogador.nivel === null ? "não informado" : jogador.nivel;
            selected.textContent = `${jogador.nome} · nível ${nivel} · X ${Math.round(jogador.x)} / Y ${Math.round(jogador.y)}`;
          };
          grupo.addEventListener("click", mostrar);
          grupo.addEventListener("keydown", (evento) => {
            if (evento.key === "Enter" || evento.key === " ") mostrar();
          });
          pins.append(grupo);
        }
      }
      timestamp.textContent = `Atualizado: ${new Date(dados.atualizado_em).toLocaleTimeString("pt-BR")}`;
    } catch (erro) {
      status.textContent = erro instanceof Error ? erro.message : "Falha ao atualizar o mapa.";
      timestamp.textContent = "Confira se o servidor e a API REST estão acessíveis.";
    }
  }

  atualizar();
  window.setInterval(atualizar, 15000);
})();
