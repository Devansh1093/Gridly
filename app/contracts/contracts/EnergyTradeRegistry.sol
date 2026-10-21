// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Local demo audit registry. It does not hold funds or prove physical delivery.
contract EnergyTradeRegistry {
    struct Trade {
        bytes32 tradeId;
        address buyer;
        address seller;
        uint256 energyWh;
        uint256 priceCentsPerKwh;
        uint256 totalCostCents;
        uint64 validUntil;
        int256 carbonDiffDeciGrams;
        uint8 carbonComparisonStatus;
        bytes32 baselineFactorHash;
        bytes32 scenarioFactorHash;
        bytes32 scoreConfigHash;
    }

    error InvalidAuthorizationSigner();
    error InvalidBuyerOrSeller();
    error SelfTrade();
    error ZeroEnergy();
    error DuplicateTrade(bytes32 tradeId);
    error AuthorizationExpired(uint64 validUntil);
    error InvalidAuthorization();
    error InvalidCarbonComparisonStatus(uint8 status);
    error NonComparableTradeMustHaveZeroDifference();
    error InvalidTotalCost(uint256 expected, uint256 supplied);

    bytes32 private constant DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );
    bytes32 private constant NAME_HASH = keccak256("EnergyTradeRegistry");
    bytes32 private constant VERSION_HASH = keccak256("1");
    bytes32 private constant TRADE_TYPEHASH = keccak256(
        "TradeAuthorization(bytes32 tradeId,address buyer,address seller,uint256 energyWh,uint256 priceCentsPerKwh,uint256 totalCostCents,uint64 validUntil,int256 carbonDiffDeciGrams,uint8 carbonComparisonStatus,bytes32 baselineFactorHash,bytes32 scenarioFactorHash,bytes32 scoreConfigHash)"
    );
    uint256 private constant SECP256K1_HALF_ORDER =
        0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0;

    address public immutable authorizationSigner;
    mapping(bytes32 => bool) public tradeExists;
    mapping(bytes32 => Trade) private storedTrades;

    event TradeRecorded(
        bytes32 indexed tradeId,
        address indexed buyer,
        address indexed seller,
        uint256 energyWh,
        uint256 priceCentsPerKwh,
        uint256 totalCostCents,
        uint64 validUntil,
        int256 carbonDiffDeciGrams,
        uint8 carbonComparisonStatus,
        bytes32 baselineFactorHash,
        bytes32 scenarioFactorHash,
        bytes32 scoreConfigHash,
        uint64 recordedAt
    );

    constructor(address signer) {
        if (signer == address(0)) revert InvalidAuthorizationSigner();
        authorizationSigner = signer;
    }

    function recordTrade(Trade calldata trade, bytes calldata authorizationSignature) external {
        if (trade.buyer == address(0) || trade.seller == address(0)) revert InvalidBuyerOrSeller();
        if (trade.buyer == trade.seller) revert SelfTrade();
        if (trade.energyWh == 0) revert ZeroEnergy();
        if (trade.tradeId == bytes32(0) || tradeExists[trade.tradeId]) revert DuplicateTrade(trade.tradeId);
        if (block.timestamp > trade.validUntil) revert AuthorizationExpired(trade.validUntil);
        if (trade.carbonComparisonStatus > 2) revert InvalidCarbonComparisonStatus(trade.carbonComparisonStatus);
        if (trade.carbonComparisonStatus != 0 && trade.carbonDiffDeciGrams != 0) {
            revert NonComparableTradeMustHaveZeroDifference();
        }
        uint256 expectedCost = (trade.energyWh * trade.priceCentsPerKwh) / 1000;
        if (trade.totalCostCents != expectedCost) revert InvalidTotalCost(expectedCost, trade.totalCostCents);
        if (_recover(_digest(trade), authorizationSignature) != authorizationSigner) revert InvalidAuthorization();

        tradeExists[trade.tradeId] = true;
        storedTrades[trade.tradeId] = trade;
        emit TradeRecorded(
            trade.tradeId,
            trade.buyer,
            trade.seller,
            trade.energyWh,
            trade.priceCentsPerKwh,
            trade.totalCostCents,
            trade.validUntil,
            trade.carbonDiffDeciGrams,
            trade.carbonComparisonStatus,
            trade.baselineFactorHash,
            trade.scenarioFactorHash,
            trade.scoreConfigHash,
            uint64(block.timestamp)
        );
    }

    function getTrade(bytes32 tradeId) external view returns (Trade memory) {
        return storedTrades[tradeId];
    }

    function _digest(Trade calldata trade) private view returns (bytes32) {
        bytes32 domainSeparator = keccak256(
            abi.encode(DOMAIN_TYPEHASH, NAME_HASH, VERSION_HASH, block.chainid, address(this))
        );
        bytes32 structHash = keccak256(
            abi.encode(
                TRADE_TYPEHASH,
                trade.tradeId,
                trade.buyer,
                trade.seller,
                trade.energyWh,
                trade.priceCentsPerKwh,
                trade.totalCostCents,
                trade.validUntil,
                trade.carbonDiffDeciGrams,
                trade.carbonComparisonStatus,
                trade.baselineFactorHash,
                trade.scenarioFactorHash,
                trade.scoreConfigHash
            )
        );
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator, structHash));
    }

    function _recover(bytes32 digest, bytes calldata signature) private pure returns (address) {
        if (signature.length != 65) return address(0);
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        if (uint256(s) > SECP256K1_HALF_ORDER || (v != 27 && v != 28)) return address(0);
        return ecrecover(digest, v, r, s);
    }
}
