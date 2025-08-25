# Example: Refactored trades/services.py methods using platform-agnostic architecture

async def update_trade_protection_levels_v2(
    user, trade_id: UUID, new_stop_loss: Decimal = None, new_take_profit: Decimal = None
) -> dict:
    """
    Platform-agnostic method to update trade protection levels.
    Uses the new TradingService for all platform operations.
    """
    trade = get_object_or_404(Trade, id=trade_id)

    if trade.account.user != user:
        raise PermissionDenied("Unauthorized to update this trade's protection levels.")

    if trade.trade_status != "open":
        raise ValidationError("Protection levels can only be updated for open trades.")

    if new_stop_loss is None and new_take_profit is None:
        raise ValidationError("At least one of new_stop_loss or new_take_profit must be provided.")

    if not trade.position_id:
        raise TradeValidationError(
            f"Trade {trade.id} does not have a position_id. Cannot update protection."
        )

    try:
        # Use platform-agnostic trading service
        trading_service = TradingService(trade.account)
        
        # Get current position details to preserve unmodified values
        position_info = await trading_service.get_position_details(trade.position_id)
        
        # Determine values to send (new values or current values)
        sl_to_send = float(new_stop_loss) if new_stop_loss is not None else position_info.stop_loss
        tp_to_send = float(new_take_profit) if new_take_profit is not None else position_info.take_profit
        
        # Execute platform operation
        platform_response = await trading_service.modify_position_protection(
            position_id=trade.position_id,
            symbol=trade.instrument,
            stop_loss=sl_to_send,
            take_profit=tp_to_send
        )
        
        # Update database
        if new_stop_loss is not None:
            trade.stop_loss = new_stop_loss
        if new_take_profit is not None:
            trade.profit_target = new_take_profit
        
        update_fields = []
        if new_stop_loss is not None:
            update_fields.append("stop_loss")
        if new_take_profit is not None:
            update_fields.append("profit_target")
            
        trade.save(update_fields=update_fields)
        
        return {
            "message": "Trade protection levels updated successfully.",
            "trade_id": str(trade.id),
            "new_stop_loss": float(trade.stop_loss) if trade.stop_loss else None,
            "new_take_profit": float(trade.profit_target) if trade.profit_target else None,
            "platform": trading_service.get_platform_name(),
            "platform_response": platform_response,
        }
        
    except Exception as e:
        logger.error(f"Failed to update protection levels for trade {trade_id}: {e}")
        if isinstance(e, (BrokerAPIError, TradeValidationError, ValidationError)):
            raise
        raise BrokerAPIError(f"Platform operation failed: {e}")
    finally:
        try:
            await trading_service.disconnect()
        except:
            pass


async def place_trade_v2(
    user,
    account_id: UUID,
    symbol: str,
    lot_size: float,
    direction: str,
    stop_loss: float = None,
    take_profit: float = None,
    order_type: str = "MARKET",
    limit_price: float = None
) -> dict:
    """
    Platform-agnostic trade placement method.
    """
    account = get_object_or_404(Account, id=account_id, user=user)
    
    if not account.active:
        raise ValidationError("Cannot place trades on inactive account.")
    
    # Validate trade request (existing risk management logic)
    # ... risk validation code ...
    
    try:
        # Use platform-agnostic trading service
        trading_service = TradingService(account)
        
        # Place trade using standardized interface
        result = await trading_service.place_trade(
            symbol=symbol,
            lot_size=lot_size,
            direction=direction,
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_type=order_type,
            limit_price=limit_price
        )
        
        # Create trade record in database
        trade = Trade.objects.create(
            account=account,
            instrument=symbol,
            direction=direction,
            size=Decimal(str(lot_size)),
            stop_loss=Decimal(str(stop_loss)) if stop_loss else None,
            profit_target=Decimal(str(take_profit)) if take_profit else None,
            position_id=result.get("position_id"),
            trade_status="open",
            # ... other fields ...
        )
        
        return {
            "message": "Trade placed successfully",
            "trade_id": str(trade.id),
            "position_id": result.get("position_id"),
            "platform": trading_service.get_platform_name(),
            "platform_response": result
        }
        
    except Exception as e:
        logger.error(f"Failed to place trade: {e}")
        if isinstance(e, (BrokerAPIError, TradeValidationError, ValidationError)):
            raise
        raise BrokerAPIError(f"Platform operation failed: {e}")
    finally:
        try:
            await trading_service.disconnect()
        except:
            pass
