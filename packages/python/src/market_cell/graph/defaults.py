from market_cell.graph.models import (
    CellGraphDefinition,
    CellGraphNode,
    CellOrganDefinition,
)


DEFAULT_ANALYSIS_GRAPH_ID = "market.default_analysis"
DEFAULT_ANALYSIS_GRAPH_VERSION = "0.1.0"


def default_analysis_graph() -> CellGraphDefinition:
    trend = "cell:technical.trend"
    volume = "cell:technical.volume"
    volatility = "cell:technical.volatility"
    regime = "cell:technical.market_regime"
    news = "cell:external.news"
    manipulation = "cell:risk.manipulation"
    root = "cell:root.decision"

    leaf_nodes = [
        CellGraphNode(trend, "technical.trend", "leaf"),
        CellGraphNode(volume, "technical.volume", "leaf"),
        CellGraphNode(volatility, "technical.volatility", "leaf"),
        CellGraphNode(regime, "technical.market_regime", "leaf"),
        CellGraphNode(news, "external.news", "leaf"),
        CellGraphNode(manipulation, "risk.manipulation", "leaf"),
    ]
    return CellGraphDefinition(
        graph_id=DEFAULT_ANALYSIS_GRAPH_ID,
        graph_version=DEFAULT_ANALYSIS_GRAPH_VERSION,
        name="Default Market Analysis",
        description="Reference graph for the current single-horizon analysis report.",
        root_node_id=root,
        nodes=[
            *leaf_nodes,
            CellGraphNode(
                node_id=root,
                cell_id="root.decision",
                execution_role="root",
                dependencies=[node.node_id for node in leaf_nodes],
            ),
        ],
        organs=[
            CellOrganDefinition(
                organ_id="organ.technical_structure",
                organ_version="0.1.0",
                name="Technical Structure",
                node_ids=[trend, volume, volatility, regime],
                output_node_ids=[trend, volume, volatility, regime],
            ),
            CellOrganDefinition(
                organ_id="organ.market_risk",
                organ_version="0.1.0",
                name="Market Risk",
                node_ids=[volatility, manipulation],
                output_node_ids=[volatility, manipulation],
            ),
            CellOrganDefinition(
                organ_id="organ.external_context",
                organ_version="0.1.0",
                name="External Context",
                node_ids=[news],
                output_node_ids=[news],
            ),
        ],
        metadata={"source": "market_cell.graph.defaults"},
    )
