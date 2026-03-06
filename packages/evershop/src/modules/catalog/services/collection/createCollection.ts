import {
  startTransaction,
  commit,
  rollback,
  insert
} from '@evershop/postgres-query-builder';
import type { PoolClient } from '@evershop/postgres-query-builder';
import { getConnection } from '../../../../lib/postgres/connection.js';
import { hookable } from '../../../../lib/util/hookable.js';
import { getValue } from '../../../../lib/util/registry.js';
import { sanitizeRawHtml } from '../../../../lib/util/sanitizeHtml.js';

export type CollectionData = {
  name: string;
  code: string;
  [key: string]: any;
};

async function insertCollectionData(
  data: CollectionData,
  connection: PoolClient
) {
  const collection = await insert('collection').given(data).execute(connection);
  return collection;
}

/**
 * Create collection service. This service will create a collection with all related data
 * @param {Object} data
 * @param {Object} context
 */
async function createCollection(
  data: CollectionData,
  context: Record<string, any>
) {
  const connection = await getConnection();
  await startTransaction(connection);
  const hookContext = { connection, ...context };
  try {
    const collectionData = await getValue<CollectionData>(
      'collectionDataBeforeCreate',
      data,
      {}
    );
    // Sanitize raw HTML blocks in EditorJS content
    if (collectionData.description) {
      sanitizeRawHtml(collectionData.description);
    }

    // Insert collection data
    const collection = await hookable(insertCollectionData, hookContext)(
      collectionData,
      connection
    );

    await commit(connection);
    return collection;
  } catch (e) {
    await rollback(connection);
    throw e;
  }
}

/**
 * Create collection service. This service will create a collection with all related data
 * @param {Object} data
 * @param {Object} context
 */
export default async (data: CollectionData, context: Record<string, any>) => {
  // Make sure the context is either not provided or is an object
  if (context && typeof context !== 'object') {
    throw new Error('Context must be an object');
  }
  const collection = await hookable(createCollection)(data, context);
  return collection;
};
