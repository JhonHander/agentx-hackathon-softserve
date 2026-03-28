import config from 'config';
import { defaultPaginationFilters } from '../../lib/util/defaultPaginationFilters.js';
import { hookAfter } from '../../lib/util/hookable.js';
import { merge } from '../../lib/util/merge.js';
import { addProcessor } from '../../lib/util/registry.js';
import {
  CreateOrderResult,
  SaveOrderArgs,
  SaveOrderContext
} from '../checkout/services/orderCreator.js';
import createShipment from './services/createShipment.js';
import registerDefaultOrderCollectionFilters from './services/registerDefaultOrderCollectionFilters.js';
import {
  changeOrderStatus,
  resolveOrderStatus
} from './services/updateOrderStatus.js';
import { updateShipmentStatus } from './services/updateShipmentStatus.js';

export default () => {
  addProcessor('configurationSchema', (schema) => {
    merge(schema, {
      properties: {
        oms: {
          type: 'object',
          properties: {
            order: {
              type: 'object',
              properties: {
                shipmentStatus: {
                  type: 'object',
                  patternProperties: {
                    '^[a-zA-Z_]+$': {
                      type: 'object',
                      properties: {
                        name: {
                          type: 'string'
                        },
                        badge: {
                          type: 'string'
                        },
                        isDefault: {
                          type: 'boolean'
                        },
                        isCancelable: {
                          type: 'boolean'
                        }
                      },
                      required: ['name', 'badge']
                    }
                  },
                  additionalProperties: false
                },
                paymentStatus: {
                  type: 'object',
                  patternProperties: {
                    '^[a-zA-Z_]+$': {
                      type: 'object',
                      properties: {
                        name: {
                          type: 'string'
                        },
                        badge: {
                          type: 'string'
                        },
                        isDefault: {
                          type: 'boolean'
                        },
                        isCancelable: {
                          type: 'boolean'
                        }
                      },
                      required: ['name', 'badge']
                    }
                  },
                  additionalProperties: false
                },
                status: {
                  type: 'object',
                  properties: {
                    new: {
                      type: 'object',
                      properties: {
                        name: {
                          type: 'string'
                        },
                        badge: {
                          type: 'string'
                        },
                        isDefault: {
                          type: 'boolean'
                        },
                        next: {
                          type: 'array',
                          items: {
                            type: 'string'
                          }
                        }
                      },
                      required: ['name', 'badge']
                    },
                    processing: {
                      type: 'object',
                      properties: {
                        name: {
                          type: 'string'
                        },
                        badge: {
                          type: 'string'
                        },
                        next: {
                          type: 'array',
                          items: {
                            type: 'string'
                          }
                        }
                      },
                      required: ['name', 'badge']
                    },
                    completed: {
                      type: 'object',
                      properties: {
                        name: {
                          type: 'string'
                        },
                        badge: {
                          type: 'string'
                        },
                        next: {
                          type: 'array',
                          items: {
                            type: 'string'
                          }
                        }
                      },
                      required: ['name', 'badge']
                    },
                    canceled: {
                      type: 'object',
                      properties: {
                        name: {
                          type: 'string'
                        },
                        badge: {
                          type: 'string'
                        },
                        next: {
                          type: 'array',
                          items: {
                            type: 'string'
                          }
                        }
                      },
                      required: ['name', 'badge']
                    },
                    closed: {
                      type: 'object',
                      properties: {
                        name: {
                          type: 'string'
                        },
                        badge: {
                          type: 'string'
                        },
                        next: {
                          type: 'array',
                          items: {
                            type: 'string'
                          }
                        }
                      },
                      required: ['name', 'badge']
                    }
                  },
                  additionalProperties: true
                },
                psoMapping: {
                  type: 'object',
                  patternProperties: {
                    '^[a-zA-Z_*]+:[a-zA-Z_*]+$': {
                      type: 'string'
                    }
                  },
                  additionalProperties: false
                },
                reStockAfterCancellation: {
                  type: 'boolean'
                }
              },
              required: ['shipmentStatus', 'paymentStatus'],
              additionalProperties: false
            },
            carriers: {
              type: 'object',
              additionalProperties: {
                type: 'object',
                properties: {
                  name: {
                    type: 'string'
                  },
                  trackingUrl: {
                    type: 'string'
                  }
                },
                required: ['name']
              }
            }
          }
        }
      }
    });
    return schema;
  });

  // Default order configuration
  const defaultOrderConfig = {
    order: {
      shipmentStatus: {
        pending: {
          name: 'Pending',
          badge: 'default',
          isDefault: true
        },
        processing: {
          name: 'Processing',
          badge: 'default',
          isDefault: false
        },
        shipped: {
          name: 'Shipped',
          badge: 'warning'
        },
        delivered: {
          name: 'Delivered',
          badge: 'success',
          isCancelable: false
        },
        canceled: {
          name: 'Canceled',
          badge: 'destructive',
          isCancelable: false
        }
      },
      paymentStatus: {
        pending: {
          name: 'Pending',
          badge: 'default',
          isDefault: true,
          isCancelable: true
        },
        paid: {
          name: 'Paid',
          badge: 'success',
          isCancelable: false
        },
        canceled: {
          name: 'Canceled',
          badge: 'destructive',
          isCancelable: true
        }
      },
      status: {
        new: {
          name: 'New',
          badge: 'default',
          isDefault: true,
          next: ['processing', 'canceled']
        },
        processing: {
          name: 'Processing',
          badge: 'default',
          next: ['completed', 'canceled']
        },
        completed: {
          name: 'Completed',
          badge: 'success',
          next: ['closed']
        },
        canceled: {
          name: 'Canceled',
          badge: 'destructive',
          next: []
        },
        closed: {
          name: 'Closed',
          badge: 'outline',
          next: []
        }
      },
      psoMapping: {
        'pending:pending': 'new',
        'pending:*': 'processing',
        'paid:*': 'processing',
        'paid:delivered': 'completed',
        'canceled:*': 'processing',
        'canceled:canceled': 'canceled'
      },
      reStockAfterCancellation: true
    },
    carriers: {
      default: {
        name: 'Default'
      },
      fedex: {
        name: 'FedEx',
        trackingUrl: 'https://www.fedex.com/fedextrack/?trknbr={trackingNumber}'
      },
      usps: {
        name: 'USPS',
        trackingUrl:
          'https://tools.usps.com/go/TrackConfirmAction?qtc_tLabels1={trackingNumber}'
      },
      ups: {
        name: 'UPS',
        trackingUrl:
          'https://www.ups.com/track?loc=en_US&tracknum={trackingNumber}'
      }
    }
  };
  config.util.setModuleDefaults('oms', defaultOrderConfig);

  // Reigtering the default filters for attribute collection
  addProcessor(
    'orderCollectionFilters',
    registerDefaultOrderCollectionFilters,
    1
  );
  addProcessor<Array<any>>(
    'orderCollectionFilters',
    (filters) => [...filters, ...defaultPaginationFilters],
    2
  );

  hookAfter(
    'changePaymentStatus',
    async (order, orderId, status, connection) => {
      const newOrderStatus = resolveOrderStatus(status, order.shipment_status);
      if (order.status === 'canceled' && newOrderStatus !== 'canceled') {
        throw new Error('Order is already canceled');
      }
      if (order.status === 'closed' && newOrderStatus !== 'closed') {
        throw new Error('Order is already closed');
      }
      await changeOrderStatus(orderId, newOrderStatus, connection);
    }
  );

  hookAfter(
    'changeShipmentStatus',
    async (order, orderId, status, connection) => {
      const newOrderStatus = resolveOrderStatus(order.payment_status, status);
      if (order.status === 'canceled' && newOrderStatus !== 'canceled') {
        throw new Error('Order is already canceled');
      }
      if (order.status === 'closed' && newOrderStatus !== 'closed') {
        throw new Error('Order is already closed');
      }

      await changeOrderStatus(orderId, newOrderStatus, connection);
    }
  );

  hookAfter<SaveOrderContext, CreateOrderResult, SaveOrderArgs>(
    'saveOrder',
    async function createShipmentForVirtualProductsOrder(
      order,
      cart,
      connection
    ) {
      if (order.no_shipping_required) {
        // Create a shipment for this order
        await createShipment(order.uuid, null, null, connection);

        // And update shipment status to delivered
        await updateShipmentStatus(order.order_id, 'delivered', connection);
      }
    }
  );
};
