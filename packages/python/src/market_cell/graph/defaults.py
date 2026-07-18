from dataclasses import replace

from market_cell.graph.models import (
    CellGraphDefinition,
    CellGraphNode,
    CellOrganDefinition,
)


DEFAULT_ANALYSIS_GRAPH_ID = "market.default_analysis"
DEFAULT_ANALYSIS_GRAPH_VERSION = "0.4.0"
LIQUIDITY_ANALYSIS_GRAPH_ID = "market.liquidity_analysis"
LIQUIDITY_ANALYSIS_GRAPH_VERSION = "0.2.0"
DERIVATIVES_ANALYSIS_GRAPH_ID = "market.derivatives_analysis"
DERIVATIVES_ANALYSIS_GRAPH_VERSION = "0.1.0"


def default_analysis_graph() -> CellGraphDefinition:
    trend = "cell:technical.trend"
    support_resistance = "cell:technical.support_resistance"
    breakout = "cell:technical.breakout"
    volume = "cell:technical.volume"
    volume_price_anomaly = "cell:risk.volume_price_anomaly"
    volatility = "cell:technical.volatility"
    regime = "cell:technical.market_regime"
    news = "cell:external.news"
    manipulation = "cell:risk.manipulation"
    root = "cell:root.decision"

    leaf_nodes = [
        CellGraphNode(trend, "technical.trend", "leaf"),
        CellGraphNode(
            support_resistance,
            "technical.support_resistance",
            "leaf",
        ),
        CellGraphNode(volume, "technical.volume", "leaf"),
        CellGraphNode(volatility, "technical.volatility", "leaf"),
        CellGraphNode(regime, "technical.market_regime", "leaf"),
        CellGraphNode(news, "external.news", "leaf"),
        CellGraphNode(
            volume_price_anomaly,
            "risk.volume_price_anomaly",
            "leaf",
        ),
    ]
    breakout_node = CellGraphNode(
        breakout,
        "technical.breakout",
        "aggregator",
        dependencies=[support_resistance],
    )
    manipulation_node = CellGraphNode(
        manipulation,
        "risk.manipulation",
        "aggregator",
        dependencies=[volume_price_anomaly],
    )
    root_dependency_ids = [
        trend,
        breakout,
        volume,
        volatility,
        regime,
        news,
        manipulation,
    ]
    return CellGraphDefinition(
        graph_id=DEFAULT_ANALYSIS_GRAPH_ID,
        graph_version=DEFAULT_ANALYSIS_GRAPH_VERSION,
        name="Default Market Analysis",
        description="Reference graph for the current single-horizon analysis report.",
        root_node_id=root,
        nodes=[
            *leaf_nodes,
            breakout_node,
            manipulation_node,
            CellGraphNode(
                node_id=root,
                cell_id="root.decision",
                execution_role="root",
                dependencies=root_dependency_ids,
            ),
        ],
        organs=[
            CellOrganDefinition(
                organ_id="organ.technical_structure",
                organ_version="0.3.0",
                name="Technical Structure",
                node_ids=[
                    trend,
                    support_resistance,
                    breakout,
                    volume,
                    volatility,
                    regime,
                ],
                output_node_ids=[
                    trend,
                    breakout,
                    volume,
                    volatility,
                    regime,
                ],
            ),
            CellOrganDefinition(
                organ_id="organ.market_risk",
                organ_version="0.2.0",
                name="Market Risk",
                node_ids=[
                    volatility,
                    volume_price_anomaly,
                    manipulation,
                ],
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


def liquidity_analysis_graph() -> CellGraphDefinition:
    """Extend the stable default graph with an explicit order-book capability."""
    base = default_analysis_graph()
    liquidity = "cell:microstructure.liquidity"
    nodes: list[CellGraphNode] = []
    for node in base.nodes:
        if node.node_id == base.root_node_id:
            nodes.append(
                CellGraphNode(
                    node_id=liquidity,
                    cell_id="microstructure.liquidity",
                    execution_role="leaf",
                )
            )
            nodes.append(
                replace(
                    node,
                    dependencies=[*node.dependencies, liquidity],
                )
            )
        else:
            nodes.append(node)

    return CellGraphDefinition(
        graph_id=LIQUIDITY_ANALYSIS_GRAPH_ID,
        graph_version=LIQUIDITY_ANALYSIS_GRAPH_VERSION,
        name="Liquidity-Aware Market Analysis",
        description=(
            "Default market analysis extended with one typed order-book "
            "liquidity snapshot."
        ),
        root_node_id=base.root_node_id,
        nodes=nodes,
        organs=[
            *base.organs,
            CellOrganDefinition(
                organ_id="organ.market_microstructure",
                organ_version="0.1.0",
                name="Market Microstructure",
                node_ids=[liquidity],
                output_node_ids=[liquidity],
                description=(
                    "Near-book spread, depth imbalance, concentration, and "
                    "liquidity fragility."
                ),
            ),
        ],
        metadata={
            "source": "market_cell.graph.defaults",
            "base_graph_id": base.graph_id,
            "base_graph_version": base.graph_version,
        },
    )


def derivatives_analysis_graph() -> CellGraphDefinition:
    """Extend the stable default graph with typed derivatives positioning."""
    base = default_analysis_graph()
    positioning = "cell:crypto.funding_open_interest"
    nodes: list[CellGraphNode] = []
    for node in base.nodes:
        if node.node_id == base.root_node_id:
            nodes.append(
                CellGraphNode(
                    node_id=positioning,
                    cell_id="crypto.funding_open_interest",
                    execution_role="leaf",
                )
            )
            nodes.append(
                replace(
                    node,
                    dependencies=[*node.dependencies, positioning],
                )
            )
        else:
            nodes.append(node)

    return CellGraphDefinition(
        graph_id=DERIVATIVES_ANALYSIS_GRAPH_ID,
        graph_version=DERIVATIVES_ANALYSIS_GRAPH_VERSION,
        name="Derivatives Positioning Market Analysis",
        description=(
            "Default market analysis extended with one typed funding-rate, "
            "open-interest, and mark-price time series."
        ),
        root_node_id=base.root_node_id,
        nodes=nodes,
        organs=[
            *base.organs,
            CellOrganDefinition(
                organ_id="organ.derivatives_positioning",
                organ_version="0.1.0",
                name="Derivatives Positioning",
                node_ids=[positioning],
                output_node_ids=[positioning],
                description=(
                    "Funding crowding, synchronized open-interest change, "
                    "deleveraging, and leverage-driven volatility risk."
                ),
            ),
        ],
        metadata={
            "source": "market_cell.graph.defaults",
            "base_graph_id": base.graph_id,
            "base_graph_version": base.graph_version,
        },
    )
